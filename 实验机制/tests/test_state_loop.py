import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Event, Selection, Understanding, Generated, Usage
from wsc.state_delta import delta
from wsc_experimental.state_writeback import write_back


class StateLoopTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.core = WSC(Store(str(Path(self.dir.name) / "state.db"),
                              session_id="s", workspace="w"),
                        access=lambda *a: True)
        self.ids = self.core.ingest([
            Event(id="m1", kind="message", role="assistant", text="observed one",
                  payload={"type": "message"}, observed_at="2026-11-17T01:00:00Z"),
            Event(id="m2", kind="message", role="assistant", text="observed two",
                  payload={"type": "message"}, observed_at="2026-11-17T02:00:00Z"),
        ])
        self.core.presented("req", tuple(self.ids), receiver="model")

    def tearDown(self):
        self.dir.cleanup()

    def test_write_back_records_without_publishing(self):
        def generator(material):
            return Generated(Selection(new_understandings=(
                Understanding(text="refined judgment", kind="fact",
                              sources=(material["events"][0]["id"],)),)), Usage(output=7))
        records = write_back(self.core, self.core.capture(), generator, producer="turn-model")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["revision"], 1)
        self.assertEqual(records[0]["producer"], "turn-model")
        with self.core.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM views").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0)
        self.assertEqual(self.core.metrics()["usage"]["output"]["known_sum"], 7)

    def test_write_back_failure_keeps_ledger_and_records_usage(self):
        def generator(material):
            raise RuntimeError("model down")
        with self.assertRaises(RuntimeError):
            write_back(self.core, self.core.capture(), generator, producer="turn-model")
        with self.core.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM understandings").fetchone()[0], 0)
        self.assertEqual(self.core.metrics()["usage"]["output"]["known_sum"], 0)

    def test_delta_added_revised_expired(self):
        first = self.core.remember(Understanding(text="v1", kind="fact",
                                                 sources=("m1",)), producer="p")
        other = self.core.remember(Understanding(text="other", kind="fact",
                                                 sources=("m2",)), producer="p")
        with self.core.store.connect() as db:
            from wsc.understanding import all_records
            records = all_records(db)
            prefix = self.core.snapshot_content(self.core.capture())[0]
        self.assertEqual(delta([first["ref"], other["ref"]], records, prefix),
                         {"added": [], "revised": [], "expired": []})
        second = self.core.remember(Understanding(text="v2", kind="fact", sources=("m1",),
                                                  id=first["id"], expected_revision=1), producer="p")
        gone = self.core.remember(Understanding(text="retired", kind="fact", sources=("m2",),
                                                id=other["id"], expected_revision=1,
                                                status="invalidated"), producer="p")
        with self.core.store.connect() as db:
            records = all_records(db)
        result = delta([first["ref"], other["ref"]], records, prefix)
        self.assertEqual(result["revised"], [{"ref": second["ref"], "previous": first["ref"]}])
        self.assertEqual(result["expired"], [other["ref"]])
        self.assertEqual(result["added"], [])
        fresh = self.core.remember(Understanding(text="new", kind="fact",
                                                 sources=("m2",)), producer="p")
        with self.core.store.connect() as db:
            records = all_records(db)
        self.assertEqual(delta([first["ref"], other["ref"]], records, prefix)["added"],
                         [fresh["ref"]])


if __name__ == "__main__":
    unittest.main()