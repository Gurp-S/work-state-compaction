import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Selection, Understanding, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter

TIMES = ["2026-11-17T01:00:00Z", "2026-11-17T02:00:00Z", "2026-11-17T03:00:00Z",
         "2026-11-17T04:00:00Z", "2026-11-17T05:00:00Z"]


class StateFirstViewTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.core = WSC(Store(self.root / "state.db", session_id="s", workspace=str(self.root)),
                        access=lambda *args: True)
        items = [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "task"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "V1 passed"}]},
            {"type": "function_call", "name": "edit", "call_id": "c1",
             "arguments": json.dumps({"file_path": "a.py", "new_string": "x"})},
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "V2 checked"}]},
        ]
        self.ids = self.core.ingest(CodexCheckpointAdapter().import_items(
            items, thread_id="t", observed_at=TIMES))
        self.core.presented("req", tuple(self.ids), receiver="model")

    def tearDown(self):
        self.dir.cleanup()

    def stale_entry(self):
        return self.core.remember(Understanding(
            text="V1 passed tests", kind="verification", sources=(self.ids[1],),
            observed_at=TIMES[1], invalid_when={"file_changed": "a.py"}), producer="p")

    def current_entry(self):
        return self.core.remember(Understanding(
            text="V2 checked after edit", kind="verification", sources=(self.ids[4],),
            observed_at=TIMES[4]), producer="p")

    def test_empty_selection_presents_current_entries(self):
        record = self.current_entry()
        view = self.core.prepare(self.core.capture(), Selection(), producer="p")
        body = self.core.view(view)["body"]
        self.assertEqual([r["ref"] for r in body["understandings"]], [record["ref"]])

    def test_expired_entry_is_not_presented_by_default(self):
        self.stale_entry()
        view = self.core.prepare(self.core.capture(), Selection(), producer="p")
        self.assertEqual(self.core.view(view)["body"]["understandings"], [])

    def test_selecting_a_non_current_entry_is_refused(self):
        stale = self.stale_entry()
        with self.assertRaisesRegex(WSCError, "state_entry_not_current"):
            self.core.prepare(self.core.capture(),
                              Selection(understanding_refs=(stale["ref"],)), producer="p")

    def test_new_understandings_written_in_prepare_are_presented(self):
        view = self.core.prepare(self.core.capture(), Selection(new_understandings=(
            Understanding(text="fresh judgment", kind="fact", sources=(self.ids[4],)),)),
            producer="p")
        body = self.core.view(view)["body"]
        self.assertEqual([r["text"] for r in body["understandings"]], ["fresh judgment"])

    def test_same_selection_revision_presents_the_new_head(self):
        old = self.current_entry()
        view = self.core.prepare(self.core.capture(), Selection(
            understanding_refs=(old["ref"],),
            new_understandings=(Understanding(text="revised judgment", kind="fact",
                sources=(self.ids[4],), id=old["id"], expected_revision=1),)), producer="p")
        body = self.core.view(view)["body"]
        self.assertEqual([r["revision"] for r in body["understandings"]], [2])
        self.assertEqual([r["text"] for r in body["understandings"]], ["revised judgment"])

    def test_working_state_leads_the_checkpoint_and_carries_state_fields(self):
        record = self.current_entry()
        view = self.core.prepare(self.core.capture(), Selection(), producer="p")
        op = self.core.stage(view, directory=self.root / "out",
                             adapter=RecordedCodexCheckpointAdapter())
        items = self.core.package(op)["items"]
        facts = json.loads(items[0]["content"][0]["text"])
        self.assertEqual(facts["kind"], "working_state")
        entry = facts["model_records"][0]
        self.assertEqual(entry["ref"], record["ref"])
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["observed_at"], TIMES[4])
        self.assertIsNone(entry["valid_until"])
        self.assertIsNone(entry["invalid_when"])
        self.assertEqual(items[1]["role"], "user")


    def test_state_changes_report_delta_since_installed_presentation(self):
        from wsc.store import setmeta
        first = self.current_entry()
        other = self.core.remember(Understanding(text="side note", kind="fact",
                                                 sources=(self.ids[1],)), producer="p")
        view = self.core.prepare(self.core.capture(), Selection(), producer="p")
        self.assertNotIn("state_changes", self.core.view(view)["body"])
        with self.core.store.transaction() as db:
            setmeta(db, "head", view)
        second = self.core.remember(Understanding(text="revised", kind="fact",
            sources=(self.ids[4],), id=first["id"], expected_revision=1), producer="p")
        self.core.remember(Understanding(text="retired", kind="fact", sources=(self.ids[1],),
            id=other["id"], expected_revision=1, status="invalidated"), producer="p")
        fresh = self.core.remember(Understanding(text="new finding", kind="fact",
                                                 sources=(self.ids[4],)), producer="p")
        view = self.core.prepare(self.core.capture(), Selection(), producer="p")
        body = self.core.view(view)["body"]
        expected = {"added": [fresh["ref"]],
                    "revised": [{"ref": second["ref"], "previous": first["ref"]}],
                    "expired": [other["ref"]]}
        self.assertEqual(body["state_changes"], expected)
        op = self.core.stage(view, directory=self.root / "out",
                             adapter=CodexCheckpointAdapter())
        facts = json.loads(self.core.package(op)["items"][0]["content"][0]["text"])
        self.assertEqual(facts["state_changes"], expected)


if __name__ == "__main__":
    unittest.main()