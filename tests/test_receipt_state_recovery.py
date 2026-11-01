"""Receipt state recovery, persisted-count repair and stored-type strictness.

Each test breaks one persisted structure and asserts what the design promises:
a lost cursor is rebuilt from a chain that proves itself (never from GENESIS
assumed to be empty), the count only grows for receipts that were actually
chained, a verified full audit repairs whatever the count claimed, and a state
value SQLite had to coerce is refused instead of read as a checkpoint.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wsc import audit_cache, events, integrity
from wsc.contracts import Event, WSCError
from wsc.core import WSC
from wsc.store import Store


class _Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-recover-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *a: True)
        self.core.ingest([Event("e1", "observation", {}, text="one"),
                          Event("e2", "observation", {}, text="two"),
                          Event("e3", "observation", {}, text="three")])
        self.present("r1", ("e1", "e2"))
        self.present("r2", ("e1",))
        self.present("r3", ("e3",))

    def present(self, request_id, source_ids):
        with self.core.store.transaction() as db:
            integrity.install_receipts(db)
            events.presented(db, request_id, tuple(source_ids), "model")

    def state(self, db):
        return db.execute("SELECT chained_through, head, receipt_count FROM wsc_receipt_state_v1 "
                          "WHERE name='receipts'").fetchone()

    def lose_state(self):
        with self.core.store.transaction() as db:
            db.execute("DELETE FROM wsc_receipt_state_v1")

    def tamper_receipt(self, receipt_id="r1", old="e2", new="e9"):
        with self.core.store.transaction() as db:
            db.execute("DROP TRIGGER IF EXISTS wsc_receipts_append_only_update")
            db.execute("UPDATE presentations SET data=replace(data, ?, ?) WHERE id=?",
                       (old, new, receipt_id))


class ReceiptStateRecovery(_Base):
    def test_lost_state_is_rebuilt_from_the_chain_and_counted_once(self):
        with self.core.store.transaction() as db:
            before = db.execute("SELECT chained_through, head FROM wsc_receipt_state_v1").fetchone()
        self.lose_state()
        with self.core.store.transaction() as db:
            report = integrity.advance_receipts(db)
            self.assertEqual((report["scanned"], report["inserted"], report["count"]), (3, 0, 3))
            after = self.state(db)
            self.assertEqual((after[0], after[1], after[2]), (before[0], before[1], 3))
            again = integrity.advance_receipts(db)
            self.assertEqual((again["scanned"], again["inserted"], again["count"]), (0, 0, 3))

    def test_lost_state_still_links_new_receipts(self):
        self.lose_state()
        self.present("r4", ("e2",))
        with self.core.store.transaction() as db:
            self.assertEqual(self.state(db)[2], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0], 4)
            self.assertEqual(integrity.advance_receipts(db)["count"], 4)

    def test_tampered_receipt_refuses_recovery(self):
        self.tamper_receipt()
        self.lose_state()
        with self.assertRaises(WSCError) as caught:
            with self.core.store.transaction() as db:
                integrity.advance_receipts(db)
        self.assertIn("receipt_state_unrecoverable", str(caught.exception))
        with self.core.store.transaction() as db:
            self.assertIsNone(self.state(db))

    def test_chain_hole_refuses_recovery(self):
        with self.core.store.transaction() as db:
            db.execute("DROP TRIGGER IF EXISTS wsc_receipt_chain_append_only_delete")
            db.execute("DELETE FROM wsc_receipt_chain_v1 WHERE rowid_=2")
        self.lose_state()
        with self.assertRaises(WSCError) as caught:
            with self.core.store.transaction() as db:
                integrity.advance_receipts(db)
        self.assertIn("receipt_state_unrecoverable", str(caught.exception))

    def test_failed_recovery_rolls_back(self):
        self.lose_state()
        with mock.patch.object(integrity, "_save_receipts", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                with self.core.store.transaction() as db:
                    integrity.advance_receipts(db)
        with self.core.store.transaction() as db:
            self.assertIsNone(self.state(db))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0], 3)

    def test_full_audit_repairs_wrong_positive_count(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=7 WHERE name='receipts'")
            report = integrity.verify_receipts(db, full=True)
            self.assertTrue(report["ok"])
            self.assertEqual(report["count"], 3)
            self.assertEqual(self.state(db)[2], 3)

    def test_full_audit_backfills_unknown_count(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=-1 WHERE name='receipts'")
            report = integrity.verify_receipts(db, full=True)
            self.assertTrue(report["ok"])
            self.assertEqual(report["count"], 3)
            self.assertEqual(self.state(db)[2], 3)

    def test_incremental_audit_does_not_repair_count(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=7 WHERE name='receipts'")
            report = integrity.verify_receipts(db)
            self.assertTrue(report["ok"])
            self.assertEqual(self.state(db)[2], 7)

    def test_failed_full_audit_does_not_touch_count(self):
        self.tamper_receipt()
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=7 WHERE name='receipts'")
            report = integrity.verify_receipts(db, full=True)
            self.assertFalse(report["ok"])
            self.assertEqual(self.state(db)[2], 7)


class StoredStateTypes(_Base):
    def put(self, column, value):
        with self.core.store.transaction() as db:
            db.execute(f"UPDATE wsc_receipt_state_v1 SET {column}=? WHERE name='receipts'", (value,))

    def test_integer_state_is_read(self):
        with self.core.store.transaction() as db:
            count, chained, head = integrity.receipt_status(db)
            self.assertEqual((count, chained), (3, 3))
            self.assertEqual(len(head), 64)

    def test_real_count_is_refused(self):
        self.put("receipt_count", 1.5)
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_count_invalid", str(caught.exception))

    def test_text_count_is_refused(self):
        # INTEGER affinity stores "1" as an integer, so only a value that stays
        # TEXT reaches the reader as a TEXT state.
        self.put("receipt_count", "not-a-number")
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_count_invalid", str(caught.exception))

    def test_null_count_is_refused(self):
        with self.core.store.transaction() as db:
            head = db.execute("SELECT head FROM wsc_receipt_state_v1").fetchone()[0]
            db.execute("ALTER TABLE wsc_receipt_state_v1 RENAME TO wsc_receipt_state_old")
            db.execute("CREATE TABLE wsc_receipt_state_v1(name TEXT PRIMARY KEY, "
                       "chained_through INTEGER, head TEXT, receipt_count INTEGER)")
            db.execute("INSERT INTO wsc_receipt_state_v1 VALUES ('receipts', 3, ?, NULL)", (head,))
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_count_invalid", str(caught.exception))

    def test_negative_position_is_refused(self):
        self.put("chained_through", -1)
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_state_invalid", str(caught.exception))

    def test_real_position_is_refused(self):
        self.put("chained_through", 2.5)
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_state_invalid", str(caught.exception))

    def test_malformed_head_is_refused(self):
        self.put("head", "abc")
        with self.core.store.transaction() as db:
            with self.assertRaises(WSCError) as caught:
                integrity.receipt_status(db)
        self.assertIn("receipt_state_invalid", str(caught.exception))

    def test_checkpoint_with_real_count_is_not_reused(self):
        with self.core.store.transaction() as db:
            self.assertTrue(audit_cache.audit_receipts_cached(db, session_id="s")["ok"])
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_integrity_audits_v1 SET audited_receipt_count=1.5")
        with self.core.store.transaction() as db:
            report = audit_cache.audit_receipts_cached(db, session_id="s")
            self.assertFalse(report["reused"])
            self.assertTrue(report["ok"])


class DeliveredLookup(_Base):
    def statements(self, db, source_id):
        seen = []
        db.set_trace_callback(seen.append)
        try:
            found = integrity.is_delivered(db, source_id, verified=True)
        finally:
            db.set_trace_callback(None)
        return found, len(seen)

    def test_hit_and_miss(self):
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.is_delivered(db, "e1", verified=True))
            self.assertTrue(integrity.is_delivered(db, "e3", verified=True))
            self.assertFalse(integrity.is_delivered(db, "e9", verified=True))

    def test_forged_index_row_is_not_a_delivery(self):
        with self.core.store.transaction() as db:
            db.execute("INSERT INTO wsc_receipt_sources_v1 VALUES ('e9','r1')")
            self.assertFalse(integrity.is_delivered(db, "e9", verified=True))

    def test_dropped_index_is_rebuilt_instead_of_missing(self):
        with self.core.store.transaction() as db:
            db.execute("DROP TABLE wsc_receipt_sources_v1")
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.is_delivered(db, "e2", verified=True))

    def test_stale_coverage_is_rebuilt_before_a_miss(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_aux_v1 SET indexed_through=0")
        with self.core.store.transaction() as db:
            self.assertFalse(integrity.is_delivered(db, "e9", verified=True))
            self.assertEqual(integrity._index_coverage(db), 3)

    def test_miss_with_current_coverage_does_not_rebuild(self):
        with self.core.store.transaction() as db:
            self.assertFalse(integrity.is_delivered(db, "e9", verified=True))
            self.assertEqual(integrity._index_coverage(db), 3)

    def test_query_count_does_not_grow_with_candidates(self):
        with self.core.store.transaction() as db:
            one = self.statements(db, "e1")
            data = json.dumps({"source_ids": ["e1"], "receiver": "model"})
            db.executemany("INSERT INTO presentations VALUES (?,?)",
                           [(f"x{number}", data) for number in range(1000)])
            integrity.advance_receipts(db)
            many = self.statements(db, "e1")
        self.assertTrue(one[0] and many[0])
        self.assertEqual(one[1], many[1])


class AuditAfterDamage(_Base):
    """What a release does when the persisted state lies about the history."""

    def audit(self, **kwargs):
        with self.core.store.transaction() as db:
            return audit_cache.audit_receipts_cached(db, session_id="s", **kwargs)

    def checkpoint(self):
        with self.core.store.transaction() as db:
            return audit_cache.latest_checkpoint(db, "s")

    def test_wrong_positive_count_is_repaired_and_the_checkpoint_is_written(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_state_v1 SET receipt_count=7 WHERE name='receipts'")
        report = self.audit()
        self.assertTrue(report["ok"], report)
        self.assertEqual((report["count"], report["checkpoint_count"]), (3, 3))
        self.assertEqual(self.checkpoint()["count"], 3)
        with self.core.store.transaction() as db:
            self.assertEqual(self.state(db)[2], 3)
        self.assertTrue(self.audit()["reused"])

    def test_tampered_history_is_still_refused(self):
        self.tamper_receipt()
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "receipt_audit_failed")
        self.assertIsNone(self.checkpoint())

    def test_lost_state_is_rebuilt_by_the_audit(self):
        with self.core.store.transaction() as db:
            before = db.execute("SELECT chained_through, head FROM wsc_receipt_state_v1").fetchone()
        self.lose_state()
        report = self.audit()
        self.assertTrue(report["ok"], report)
        self.assertEqual((report["scope"], report["reused"], report["count"]), ("full", False, 3))
        with self.core.store.transaction() as db:
            after = self.state(db)
        self.assertEqual((after[0], after[1], after[2]), (before[0], before[1], 3))
        self.assertTrue(self.audit()["reused"])

    def test_lost_state_is_rebuilt_before_the_anchor_is_compared(self):
        with self.core.store.transaction() as db:
            head = db.execute("SELECT head FROM wsc_receipt_state_v1").fetchone()[0]
        self.lose_state()
        self.assertTrue(self.audit(anchor=head)["ok"])
        self.lose_state()
        with self.assertRaisesRegex(WSCError, "integrity_anchor_mismatch"):
            self.audit(anchor=integrity.GENESIS)

    def test_unprovable_chain_is_not_repaired(self):
        self.tamper_receipt()
        self.lose_state()
        with self.assertRaisesRegex(WSCError, "receipt_state_unrecoverable"):
            self.audit()
        with self.core.store.transaction() as db:
            self.assertIsNone(self.state(db))
        self.assertIsNone(self.checkpoint())

    def test_a_confirmed_audit_ending_on_another_head_is_refused(self):
        with self.core.store.transaction() as db:
            report = integrity.verify_receipts(db, full=True)
        moved = dict(report, head=integrity.GENESIS)
        with mock.patch("wsc.integrity.verify_receipts", return_value=moved):
            with self.assertRaisesRegex(WSCError, "receipt_audit_range_moved"):
                self.audit()
        self.assertIsNone(self.checkpoint())


class IndexRecovery(_Base):
    """A rebuilt cursor must not vouch for an index it did not rebuild."""

    def drop_index_row(self, source_id="e2", receipt_id="r1"):
        with self.core.store.transaction() as db:
            db.execute("DELETE FROM wsc_receipt_sources_v1 WHERE source_id=? AND receipt_id=?",
                       (source_id, receipt_id))

    def test_recovered_cursor_rebuilds_the_index_before_a_miss(self):
        self.drop_index_row()
        self.lose_state()
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.is_delivered(db, "e2", verified=True))
            self.assertEqual(integrity._index_coverage(db), 3)

    def test_recovery_rebuilds_a_dropped_index_table(self):
        with self.core.store.transaction() as db:
            db.execute("DROP TABLE wsc_receipt_sources_v1")
        self.lose_state()
        with self.core.store.transaction() as db:
            integrity.advance_receipts(db)
            self.assertTrue(integrity.is_delivered(db, "e2", verified=True))
            self.assertEqual(integrity._index_coverage(db), 3)

    def test_recovery_then_a_new_receipt_keeps_the_index_complete(self):
        self.drop_index_row()
        self.lose_state()
        self.present("r4", ("e2",))
        with self.core.store.transaction() as db:
            self.assertEqual(self.state(db)[2], 4)
            self.assertTrue(integrity.is_delivered(db, "e2", verified=True))
            self.assertEqual(integrity._index_coverage(db), 4)


class OrphanChainRecords(_Base):
    """A chain row with no receipt is not history, wherever its rowid sits."""

    def add_orphan(self, rowid, receipt_id="orphan"):
        with self.core.store.transaction() as db:
            db.execute("INSERT INTO wsc_receipt_chain_v1(rowid_, receipt_id, source_ids, link) "
                       "VALUES (?,?,'',?)", (rowid, receipt_id, "0" * 64))

    def audit(self):
        with self.core.store.transaction() as db:
            return audit_cache.audit_receipts_cached(db, session_id="s")

    def checkpoint(self):
        with self.core.store.transaction() as db:
            return audit_cache.latest_checkpoint(db, "s")

    def snapshot(self, core=None):
        """State row, index coverage, chain rows, index rows."""
        core = core or self.core
        with core.store.transaction() as db:
            return (self.state(db), integrity._index_coverage(db),
                    db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM wsc_receipt_sources_v1").fetchone()[0])

    def test_orphan_below_the_cursor_refuses_recovery(self):
        self.assertTrue(self.audit()["ok"])
        checkpoint = self.checkpoint()
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_aux_v1 SET indexed_through=1")
        self.add_orphan(0)
        self.lose_state()
        with self.assertRaisesRegex(WSCError, "receipt_state_unrecoverable"):
            with self.core.store.transaction() as db:
                integrity.ensure_receipt_state(db)
        self.assertEqual((None, 1, 4, 4), self.snapshot())
        self.assertEqual(checkpoint, self.checkpoint())
        with self.assertRaisesRegex(WSCError, "receipt_state_unrecoverable"):
            self.audit()
        self.assertEqual(checkpoint, self.checkpoint())

    def test_orphan_above_the_cursor_refuses_recovery(self):
        self.add_orphan(9)
        self.lose_state()
        with self.assertRaisesRegex(WSCError, "receipt_state_unrecoverable"):
            with self.core.store.transaction() as db:
                integrity.ensure_receipt_state(db)
        self.assertIsNone(self.snapshot()[0])

    def test_normal_recovery_is_unaffected(self):
        with self.core.store.transaction() as db:
            before = tuple(self.state(db))
        self.lose_state()
        with self.core.store.transaction() as db:
            self.assertEqual((3, before[0], before[1]), integrity.ensure_receipt_state(db))
            self.assertEqual(before, tuple(self.state(db)))
            self.assertEqual(3, integrity._index_coverage(db))
            self.assertTrue(integrity.is_delivered(db, "e2", verified=True))
            self.assertEqual((3, before[0], before[1]), integrity.ensure_receipt_state(db))
        self.present("r4", ("e2",))
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.verify_receipts(db)["ok"])
            self.assertEqual(4, self.state(db)[2])

    def test_failed_recovery_leaves_nothing_behind_after_reopen(self):
        self.audit()
        checkpoint = self.checkpoint()
        with self.core.store.transaction() as db:
            db.execute("UPDATE wsc_receipt_aux_v1 SET indexed_through=1")
        self.add_orphan(0)
        self.lose_state()
        with self.assertRaisesRegex(WSCError, "receipt_state_unrecoverable"):
            with self.core.store.transaction() as db:
                integrity.ensure_receipt_state(db)
        reopened = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                       access=lambda *a: True)
        self.assertEqual((None, 1, 4, 4), self.snapshot(reopened))
        with reopened.store.transaction() as db:
            self.assertEqual(checkpoint, audit_cache.latest_checkpoint(db, "s"))


if __name__ == "__main__":
    unittest.main()
