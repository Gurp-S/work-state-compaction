import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import Store, WSC, Event, Understanding, WSCError
from wsc.events import rows
from wsc.state_view import current_entries, entry_expired, latest_observed_at


def edit_event(id, path, at):
    return Event(id=id, kind="call", call_id=id,
                 payload={"name": "edit", "arguments": json.dumps({"file_path": path})},
                 observed_at=at)


class StateViewTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.core = WSC(Store(str(Path(self.dir.name) / "state.db"),
                              session_id="s", workspace="w"),
                        access=lambda *a: True)
        self.core.ingest([
            Event(id="m1", kind="message", role="assistant", text="V1 passed",
                  payload={"type": "message"}, observed_at="2026-11-17T01:00:00Z"),
            edit_event("c1", "a.py", "2026-11-17T02:00:00Z"),
            Event(id="m2", kind="message", role="assistant", text="re-verified V2",
                  payload={"type": "message"}, observed_at="2026-11-17T03:00:00Z"),
        ])
        with self.core.store.connect() as db:
            self.prefix = rows(db)

    def tearDown(self):
        self.dir.cleanup()

    def entry(self, **kw):
        base = dict(text="V1 passed tests", kind="fact", sources=("m1",),
                    observed_at="2026-11-17T01:00:00Z",
                    invalid_when={"file_changed": "a.py"})
        base.update(kw)
        return self.core.remember(Understanding(**base), producer="p")

    def test_edit_after_entry_source_invalidates(self):
        record = self.entry()
        self.assertTrue(entry_expired(record, self.prefix, latest_observed_at(self.prefix)))
        self.assertEqual(current_entries([record], self.prefix), [])

    def test_edit_before_entry_source_keeps_entry(self):
        record = self.entry(sources=("m2",), text="V2 verified")
        self.assertFalse(entry_expired(record, self.prefix, latest_observed_at(self.prefix)))
        self.assertEqual(current_entries([record], self.prefix), [record])

    def test_unsourced_entry_invalidated_by_any_matching_edit(self):
        record = self.entry(sources=())
        self.assertTrue(entry_expired(record, self.prefix, latest_observed_at(self.prefix)))

    def test_other_path_edit_does_not_invalidate(self):
        record = self.entry(invalid_when={"file_changed": "b.py"})
        self.assertFalse(entry_expired(record, self.prefix, latest_observed_at(self.prefix)))

    def test_non_active_status_excluded(self):
        record = self.entry(status="superseded", invalid_when=None)
        self.assertEqual(current_entries([record], self.prefix), [])

    def test_valid_until_against_newest_observation(self):
        expired = self.entry(invalid_when=None, valid_until="2026-11-17T02:30:00Z")
        living = self.entry(invalid_when=None, valid_until="2026-11-17T04:00:00Z")
        self.assertEqual(current_entries([expired, living], self.prefix), [living])

    def test_unsupported_condition_refused(self):
        record = self.entry(invalid_when={"mood_changed": "x"})
        with self.assertRaises(WSCError):
            entry_expired(record, self.prefix, latest_observed_at(self.prefix))


if __name__ == "__main__":
    unittest.main()