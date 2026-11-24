"""Shadow Tree (§12.7): rehearse structural change, refuse on violations, publish atomically."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CSMError, CsmStore, Event, MemoryCandidate  # noqa: E402

T1 = "2026-11-01T10:00:00+00:00"


class ShadowFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = CSM(CsmStore(self.root / "memory.db", namespace="user:lea"),
                        clock=lambda: T1)
        self.core.ingest([Event("e1", "chat", {"text": "prod deploys with k8s"},
                                observed_at=T1)])
        self.memory = self.core.remember([MemoryCandidate(
            entity="project a", slot="deployment engine", value="Kubernetes",
            contexts=("production",), source_ids=("e1",))])[0]
        self.node = self.core.create_node(name="project a", entity_anchor="project a", status="active")
        self.core.mount(self.memory["memory_id"], node_id=self.node["node_id"])

    def operations(self):
        return [{"op": "create_node", "name": "project b", "parent_id": "MemorySpace"},
                {"op": "mount", "memory_id": self.memory["memory_id"],
                 "node_id": self.node["node_id"]}]


class ShadowTests(ShadowFixture):
    def test_evaluate_reports_candidate_metrics_without_writing(self):
        before = self.core.tree()
        report = self.core.shadow(self.operations())
        self.assertTrue(report["ok"])
        self.assertEqual(report["operations"], 2)
        self.assertEqual(report["improvement"]["nodes"], 1)
        self.assertEqual(report["baseline"]["mounts"], 1)
        self.assertEqual(self.core.tree()["revision"], before["revision"])

    def test_apply_publishes_created_node(self):
        result = self.core.shadow_apply(self.operations())
        self.assertTrue(result["report"]["ok"])
        names = {node["name"] for node in self.core.tree()["nodes"]}
        self.assertIn("project b", names)

    def test_unreachable_mount_is_refused_and_nothing_is_published(self):
        operations = self.operations() + [{"op": "retire", "node_id": self.node["node_id"]}]
        report = self.core.shadow(operations)
        self.assertFalse(report["ok"])
        self.assertEqual(report["violations"][0]["code"], "tree_mount_unreachable")
        revision = self.core.tree()["revision"]
        with self.assertRaises(CSMError) as caught:
            self.core.shadow_apply(operations)
        self.assertEqual(str(caught.exception), "shadow_invariant_violation")
        self.assertEqual(self.core.tree()["revision"], revision)

    def test_entity_anchor_mismatch_is_a_violation(self):
        other = self.core.create_node(name="project z", entity_anchor="project z", status="active")
        report = self.core.shadow([
            {"op": "mount", "memory_id": self.memory["memory_id"],
             "node_id": other["node_id"]}])
        self.assertFalse(report["ok"])
        self.assertEqual(report["violations"][0]["code"], "tree_scope_entity_mismatch")

    def test_cycle_is_a_violation(self):
        parent = self.core.create_node(name="group", entity_anchor="group", status="active")
        report = self.core.shadow([
            {"op": "create_node", "name": "child", "parent_id": parent["node_id"]}])
        self.assertTrue(report["ok"])
        report = self.core.shadow([
            {"op": "merge", "source": parent["node_id"], "target": "MemorySpace"}])
        self.assertTrue(report["ok"])


if __name__ == "__main__":
    unittest.main()


