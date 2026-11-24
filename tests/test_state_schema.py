import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Understanding, WSCError
from wsc.contracts import encode
from wsc.understanding import all_records, resolve


class StateSchemaTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.core = WSC(Store(str(Path(self.dir.name) / "state.db"),
                              session_id="s", workspace="w"),
                        access=lambda *a: True)

    def tearDown(self):
        self.dir.cleanup()

    def test_state_fields_round_trip(self):
        record = self.core.remember(Understanding(
            text="V1 passed tests", kind="fact",
            status="active", observed_at="2026-11-17T00:00:00Z",
            valid_until="2026-12-01T00:00:00Z",
            invalid_when={"file_changed": "a.py"}), producer="p")
        with self.core.store.connect() as db:
            stored = resolve(db, record["ref"])
        self.assertEqual(stored["status"], "active")
        self.assertEqual(stored["observed_at"], "2026-11-17T00:00:00Z")
        self.assertEqual(stored["valid_until"], "2026-12-01T00:00:00Z")
        self.assertEqual(stored["invalid_when"], {"file_changed": "a.py"})
        self.assertEqual(stored["revision"], 1)
        self.assertIsNone(stored["previous"])

    def test_defaults_keep_old_call_shape(self):
        record = self.core.remember(Understanding(text="plain", kind="fact"), producer="p")
        self.assertEqual(record["status"], "active")
        self.assertIsNone(record["observed_at"])
        self.assertIsNone(record["valid_until"])
        self.assertIsNone(record["invalid_when"])

    def test_revision_cas_carries_state_fields(self):
        first = self.core.remember(Understanding(text="v1", kind="fact"), producer="p")
        second = self.core.remember(Understanding(
            text="v2", kind="fact", id=first["id"], expected_revision=1,
            status="superseded"), producer="p")
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["previous"], first["ref"])
        self.assertEqual(second["status"], "superseded")
        with self.assertRaises(WSCError):
            self.core.remember(Understanding(
                text="v3", kind="fact", id=first["id"], expected_revision=1), producer="p")

    def test_invalid_state_values_refused(self):
        for value, reason in (
            (Understanding(text="x", kind="fact", status="maybe"), "understanding_status_invalid"),
            (Understanding(text="x", kind="fact", invalid_when=["a"]), "invalid_understanding_invalid_when"),
            (Understanding(text="x", kind="fact", observed_at="  "), "understanding_time_invalid"),
            (Understanding(text="x", kind="fact", valid_until=""), "understanding_time_invalid"),
        ):
            with self.assertRaises(WSCError) as caught:
                self.core.remember(value, producer="p")
            self.assertEqual(str(caught.exception), reason)

    def test_legacy_journal_row_reads_with_defaults(self):
        legacy = {"text": "old", "kind": "fact", "sources": [], "scope": None,
                  "id": "legacy1", "revision": 1, "ref": "legacy1@1",
                  "producer": "p", "previous": None}
        with self.core.store.transaction() as db:
            db.execute("INSERT INTO understandings VALUES (?,?,?,?)",
                       ("legacy1", 1, "legacy1@1", encode(legacy)))
        with self.core.store.connect() as db:
            stored = resolve(db, "legacy1@1")
            records = all_records(db)
        self.assertEqual(stored["status"], "active")
        self.assertIsNone(stored["observed_at"])
        self.assertIsNone(stored["valid_until"])
        self.assertIsNone(stored["invalid_when"])
        self.assertEqual(records[0]["ref"], "legacy1@1")
        self.assertEqual(records[0]["status"], "active")


if __name__ == "__main__":
    unittest.main()