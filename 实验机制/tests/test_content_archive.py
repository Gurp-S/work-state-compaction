"""Atomic cold-object publication and independent complete detach handoff."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Selection, WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc_experimental.content_archive import publish_object
from wsc.publication import check_evidence
from test_contracts import DurableTestHost, message


class ContentArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-content-archive-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.core = WSC(Store(self.root / "state.db", session_id="session", workspace=str(self.root)),
                        access=lambda *args: True)
        self.adapter = CodexCheckpointAdapter()
        self.items = [message("user", "task"), message("assistant", "same observation"),
                      message("assistant", "same observation"), {"type": "reasoning", "encrypted_content": "opaque"}]
        self.ids = self.core.ingest(self.adapter.import_items(self.items, thread_id="source",
            observed_at=["time-1", "time-2", "time-3", "time-4"]))

    def test_detach_exports_independent_complete_handoff(self):
        view = self.core.prepare(self.core.capture(), Selection(), producer="offline-test")
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        host = DurableTestHost(self.root / "host.db", self.core, self.items)
        self.core.install(op, host)
        handoff = self.root / "handoff"
        detach = self.core.stage_detach(directory=handoff, adapter=self.adapter)
        package = self.core.package(detach)
        self.assertEqual(set(self.ids), set(package["evidence"]))
        for locator in package["evidence"].values():
            self.assertTrue(Path(locator["file_path"]).is_relative_to(handoff))
            if "readable_path" in locator:
                self.assertTrue(Path(locator["readable_path"]).is_relative_to(handoff))
        check_evidence(self.core, package)

    def test_atomic_object_publication_survives_competing_writers(self):
        path = self.root / "shared-object"
        payload = b"exact historical bytes" * 8192
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda _: publish_object(path, payload), range(8)))
        self.assertEqual(payload, path.read_bytes())
        self.assertFalse(list(self.root.glob(".pending-*")))
        with self.assertRaisesRegex(WSCError, "evidence_object_conflict"):
            publish_object(path, b"different")
        self.assertEqual(payload, path.read_bytes())

    def test_failed_write_does_not_expose_a_partial_object(self):
        path = self.root / "never-committed"
        with patch("wsc_experimental.content_archive.os.fsync", side_effect=OSError("disk_failure")):
            with self.assertRaisesRegex(OSError, "disk_failure"):
                publish_object(path, b"content")
        self.assertFalse(path.exists())
        self.assertFalse(list(self.root.glob(".pending-*")))


if __name__ == "__main__":
    unittest.main()