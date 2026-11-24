"""Observed host commits survive later input; lost replies stop explicitly."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc import WSC, Store, Selection, Understanding, WSCError, HostRejection
from wsc.adapters.callback import CallbackHost
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import encode
from wsc.publication import confirm
from test_contracts import DurableTestHost, message


class PublicationSettlementTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="wsc-settlement-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = self.reopen()
        self.adapter = CodexCheckpointAdapter()
        self.items = [message("user", "original request"), message("assistant", "observed diagnosis")]
        self.ids = self.core.ingest(self.adapter.import_items(self.items, thread_id="source"))
        self.host = DurableTestHost(self.root / "host.db", self.core, self.items)
        self.op = self.stage()

    def reopen(self):
        return WSC(Store(self.root / "wsc.db", session_id="session", workspace=str(self.root)),
                   access=lambda *args: True)

    def stage(self):
        view = self.core.prepare(self.core.capture(), Selection(), producer="offline_test")
        return self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)

    def append_control(self):
        item = message("user", "new constraint after installation")
        self.core.ingest(self.adapter.import_items([item], thread_id="new-control"))
        with closing(sqlite3.connect(self.host.path)) as db, db:
            state = self.host.state()
            state["items"].append(item)
            db.execute("UPDATE state SET data=? WHERE id=1", (encode(state),))
        return item

    def assert_settled_once(self, core):
        status = core.status()
        self.assertEqual("confirmed", status["operations"][0]["state"])
        self.assertEqual(1, status["generation"])
        self.assertEqual(2, status["cursor"])
        self.assertEqual(1, self.host.state()["effects"])

    def test_lost_reply_stops_explicitly_across_reopen(self):
        self.host.lose_reply = True
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, self.host)
        tail = self.append_control()
        reopened = self.reopen()
        self.assertEqual("unknown", reopened.status()["operations"][0]["state"])
        self.assertEqual(tail, self.host.state()["items"][-1])
        self.assertEqual(3, reopened.status()["source_count"])
        self.assertEqual(1, self.host.state()["effects"])
        self.assertTrue(Path(reopened.package(self.op)["evidence"][self.ids[1]]["file_path"]).is_file())
        with self.assertRaisesRegex(WSCError, "publication_pending"):
            self.stage()

    def test_later_understanding_does_not_erase_committed_installation(self):
        def commit(package):
            receipt = self.host.install(package)
            self.core.remember(Understanding("new interpretation", "hypothesis", (self.ids[1],)),
                               producer="later_model_output")
            return receipt
        self.core.install(self.op, CallbackHost(commit=commit))
        self.assert_settled_once(self.core)
        self.assertEqual("new interpretation", self.core.capture().understandings[-1]["text"])
        self.assertTrue(self.stage())

    def test_late_timeout_cannot_downgrade_concurrently_confirmed_operation(self):
        def commit(package):
            receipt = self.host.install(package)
            confirm(self.reopen(), self.op, receipt)
            raise TimeoutError("original_reply_lost_after_other_confirmation")
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, CallbackHost(commit=commit))
        self.assert_settled_once(self.core)
        self.assertEqual(1, self.core.install(self.op, self.host)["generation"])
        self.assertEqual(1, self.host.state()["effects"])
        self.assertTrue(self.stage())

    def test_late_conflicting_reply_cannot_downgrade_confirmed_operation(self):
        def commit(package):
            receipt = self.host.install(package)
            confirm(self.reopen(), self.op, receipt)
            return replace(receipt, generation=999)
        with self.assertRaisesRegex(WSCError, "host_receipt_conflict"):
            self.core.install(self.op, CallbackHost(commit=commit))
        self.assert_settled_once(self.core)
        self.assertEqual(1, self.core.install(self.op, self.host)["generation"])

    def test_late_interrupt_keeps_unknown_as_explicit_stop(self):
        def commit(package):
            self.host.install(package)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.core.install(self.op, CallbackHost(commit=commit))
        self.assertEqual("unknown", self.core.status()["operations"][0]["state"])
        self.append_control()
        reopened = self.reopen()
        self.assertEqual("unknown", reopened.status()["operations"][0]["state"])
        self.assertEqual(1, self.host.state()["effects"])
        self.assertEqual(0, reopened.status()["cursor"])

    def test_late_timeout_cannot_erase_durable_rejection(self):
        def commit(package):
            from dataclasses import asdict
            receipt = HostRejection(self.op, package["package_digest"], "session",
                                    str(self.root.resolve()), "capacity_rejected", "offline_test_host")
            confirm(self.reopen(), self.op, receipt)
            raise TimeoutError("rejection_reply_lost")
        with self.assertRaises(TimeoutError):
            self.core.install(self.op, CallbackHost(commit=commit))
        self.assertEqual("rejected", self.core.status()["operations"][0]["state"])
        self.assertEqual("capacity_rejected", self.core.install(self.op, self.host)["reason"])
        self.assertEqual(0, self.host.state()["effects"])
        self.assertTrue(self.stage())


if __name__ == "__main__":
    unittest.main()