"""Derived-state identity and count semantics for the receipt index and chain.

Each test breaks exactly one derived structure and asserts the outcome the
design promises: an index that cannot lose a receipt, a migration that repairs
an older key, a chain that reports a hole instead of hiding it, and a count that
describes the history rather than the work a single run happened to do.
"""
import json
import tempfile
import unittest
from pathlib import Path

from wsc import events, integrity
from wsc.contracts import Event, WSCError
from wsc.core import WSC
from wsc.store import Store


class IndexIdentityChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-index-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = self.open()
        self.ids = self.core.ingest([Event("e1", "observation", {}, text="hello"),
                                     Event("e2", "observation", {}, text="world")])

    def open(self, session="s"):
        return WSC(Store(self.root / "state.db", session_id=session, workspace=str(self.root)),
                   access=lambda *a: True)

    def present(self, request_id, source_ids):
        with self.core.store.transaction() as db:
            integrity.install_receipts(db)
            events.presented(db, request_id, tuple(source_ids), "model")

    def index_rows(self, db):
        return {(row[0], row[1]) for row in
                db.execute("SELECT source_id, receipt_id FROM wsc_receipt_sources_v1")}

    def test_source_presented_twice_keeps_both_receipts(self):
        self.present("r1", self.ids)
        self.present("r2", ("e1",))
        with self.core.store.transaction() as db:
            report = integrity.rebuild_receipt_index(db)
            self.assertEqual(report["rebuilt"], 3)
            self.assertEqual(self.index_rows(db), {("e1", "r1"), ("e2", "r1"), ("e1", "r2")})
            self.assertTrue(integrity.is_delivered(db, "e1"))
            self.assertTrue(integrity.is_delivered(db, "e2"))

    def test_legacy_single_column_key_is_migrated(self):
        self.present("r1", self.ids)
        with self.core.store.transaction() as db:
            integrity.verify_receipts(db, full=True)
            db.execute("DROP TABLE wsc_receipt_sources_v1")
            db.execute("CREATE TABLE wsc_receipt_sources_v1(source_id TEXT PRIMARY KEY, "
                       "receipt_id TEXT NOT NULL)")
            db.execute("INSERT INTO wsc_receipt_sources_v1 VALUES ('e1','r1')")
            db.execute("INSERT INTO wsc_receipt_sources_v1 VALUES ('ghost','r0')")
            # A database from the previous release carries no aux marker, so it
            # is migrated instead of trusted.
            db.execute("DELETE FROM wsc_receipt_aux_v1")
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.is_delivered(db, "e2"))
            key = [row[1] for row in db.execute("PRAGMA table_info(wsc_receipt_sources_v1)")
                   if row[5]]
            self.assertEqual(key, ["source_id", "receipt_id"])
            self.assertEqual(self.index_rows(db), {("e1", "r1"), ("e2", "r1")})

    def test_history_count_is_not_the_scan(self):
        for number in range(3):
            self.present(f"r{number}", self.ids)
        with self.core.store.transaction() as db:
            full = integrity.verify_receipts(db, full=True)
            self.assertEqual((full["count"], full["scanned"]), (3, 3))
        self.present("r3", ("e1",))
        with self.core.store.transaction() as db:
            incremental = integrity.verify_receipts(db)
            self.assertEqual((incremental["count"], incremental["scanned"]), (4, 1))


class ChainHoleChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wsc-chain-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *a: True)
        with self.core.store.transaction() as db:
            integrity.install(db)
        self.core.ingest([Event("e1", "observation", {}, text="one"),
                          Event("e2", "observation", {}, text="two")])

    def test_missing_event_row_is_a_mismatch_not_a_pass(self):
        with self.core.store.transaction() as db:
            self.assertTrue(integrity.verify(db, full=True)["ok"])
            db.execute("DELETE FROM events WHERE seq=1")
            with self.assertRaises(WSCError) as caught:
                integrity.verify(db, full=True)
            self.assertIn("source_integrity_mismatch", str(caught.exception))

    def test_rewritten_link_is_refused_instead_of_replaced(self):
        with self.core.store.transaction() as db:
            seq = db.execute("SELECT seq FROM wsc_event_chain_v1 ORDER BY seq DESC "
                             "LIMIT 1").fetchone()[0]
            db.execute("UPDATE wsc_event_chain_v1 SET link=? WHERE seq=?", ("f" * 64, seq))
            db.execute("UPDATE wsc_integrity_state_v1 SET chained_through=? WHERE name='events'",
                       (seq - 1,))
            with self.assertRaises(WSCError) as caught:
                integrity.advance(db)
            self.assertIn("integrity_chain_conflict", str(caught.exception))
