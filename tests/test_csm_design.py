"""CSM design slice: relations, dependencies, state tree, watermarks, proposals, time travel."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CSMError, CsmStore, Event, MemoryCandidate, MemoryQuery

T1 = "2026-11-01T10:00:00+00:00"
T2 = "2026-11-01T11:00:00+00:00"


class DesignFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = T1
        self.core = CSM(CsmStore(self.root / "memory.db", namespace="user:lea"),
                        clock=lambda: self.now)
        self.core.ingest([
            Event("e1", "chat", {"text": "prod deploys with k8s"}, observed_at=T1),
            Event("e2", "chat", {"text": "billing runs on postgres"}, observed_at=T1),
            Event("e3", "chat", {"text": "prod needs the permission first"}, observed_at=T2),
        ])

    def remember(self, **overrides):
        data = {"entity": "project a", "slot": "deployment engine", "value": "Kubernetes",
                "contexts": ("production",), "source_ids": ("e1",)}
        data.update(overrides)
        return self.core.remember([MemoryCandidate(**data)])[0]

    def query(self, **overrides):
        data = {"entity": "project a", "slot": "deployment engine"}
        data.update(overrides)
        return self.core.query(MemoryQuery(**data))


class RelationTests(DesignFixture):
    def test_confirmed_relation_expands_as_unconfirmed_context(self):
        source = self.remember()
        target = self.remember(entity="project b", slot="database", value="PostgreSQL",
                               source_ids=("e2",))
        self.core.link(kind="CONSTRAINT", subject=f"memory:{source['memory_id']}",
                       object=f"memory:{target['memory_id']}", evidence=["e1"], confirmed=True)
        result = self.query(expand=1)
        self.assertEqual(1, result["counts"].get("CURRENT_CONFIRMED"))
        unknown = [item for item in result["results"]
                   if item["classification"] == "UNKNOWN"]
        self.assertEqual(1, len(unknown))
        self.assertEqual("relation_expansion", unknown[0]["reason"])
        self.assertEqual(target["memory_id"], unknown[0]["memory_id"])
        self.assertEqual("CONSTRAINT", unknown[0]["related"]["kind"])

    def test_unconfirmed_relation_is_not_traversable(self):
        source = self.remember()
        target = self.remember(entity="project b", slot="database", value="PostgreSQL",
                               source_ids=("e2",))
        self.core.link(kind="CONSTRAINT", subject=f"memory:{source['memory_id']}",
                       object=f"memory:{target['memory_id']}", evidence=["e1"])
        result = self.query(expand=1)
        self.assertEqual(0, result["counts"].get("UNKNOWN", 0))

    def test_relation_needs_evidence(self):
        source = self.remember()
        target = self.remember(entity="project b", slot="database", value="PostgreSQL",
                               source_ids=("e2",))
        with self.assertRaises(CSMError):
            self.core.link(kind="CONSTRAINT", subject=f"memory:{source['memory_id']}",
                           object=f"memory:{target['memory_id']}", evidence=[])

    def test_dependency_impact_proposes_but_never_moves_state(self):
        source = self.remember()
        target = self.remember(entity="project b", slot="database", value="PostgreSQL",
                               source_ids=("e2",))
        edge = self.core.link(kind="CONSTRAINT", subject=f"memory:{source['memory_id']}",
                              object=f"memory:{target['memory_id']}", evidence=["e1"],
                              confirmed=True)
        impact = self.core.impact(source["memory_id"])
        self.assertEqual(["INFORMATION_GAP"], [item["effect"] for item in impact["effects"]])
        self.assertFalse(impact["cascaded"])
        self.core.set_truth(edge["rel_id"], "TRUE", evidence=["e3"])
        impact = self.core.impact(source["memory_id"])
        self.assertEqual(["REVALIDATE"], [item["effect"] for item in impact["effects"]])
        current = self.query()["results"][0]
        self.assertEqual("Kubernetes", current["value"])


class TreeTests(DesignFixture):
    def test_mount_makes_memory_reachable_from_its_node(self):
        memory = self.remember()
        node = self.core.create_node(name="平台组", entity_anchor="project a", status="active",
                                     evidence=["e1"])
        mounted = self.core.mount(memory["memory_id"], node_id=node["node_id"])
        self.assertTrue(mounted["changed"])
        self.assertEqual(node["node_id"], mounted["paths"][0]["node_id"])
        scoped = self.core.query(MemoryQuery(node_id=node["node_id"]))
        self.assertEqual(["CURRENT_CONFIRMED"],
                         [item["classification"] for item in scoped["results"]])
        self.assertEqual(node["node_id"], self.core.paths(memory["memory_id"])[0]["node_id"])

    def test_unknown_node_parks_the_attribution_as_pending(self):
        memory = self.remember()
        deferred = self.core.mount(memory["memory_id"])
        self.assertEqual("DEFER", deferred["operation"])
        pending = self.query()["results"]
        self.assertEqual(["PENDING_BINDING"], [item["classification"] for item in pending
                                               if item["classification"] == "PENDING_BINDING"])
        node = self.core.create_node(name="平台组", status="active", evidence=["e1"])
        resolved = self.core.resolve_mount(deferred["pending_id"], node_id=node["node_id"])
        self.assertEqual("resolved", resolved["status"])
        self.assertEqual([], [item for item in self.query()["results"]
                              if item["classification"] == "PENDING_BINDING"])

    def test_promotion_needs_coverage_and_contract(self):
        first = self.remember()
        second = self.remember(entity="project a", slot="database", value="PostgreSQL",
                               source_ids=("e2",))
        node = self.core.create_node(name="平台组", scope_description="platform work",
                                     evidence=["e1"])
        self.core.mount(first["memory_id"], node_id=node["node_id"], allow_candidate=True)
        self.core.mount(second["memory_id"], node_id=node["node_id"], allow_candidate=True)
        promoted = self.core.promote(node["node_id"], threshold=2, window_seconds=0)
        self.assertEqual("active", promoted["status"])
        self.assertEqual(2, len(promoted["coverage"]))
        self.assertEqual(2, self.core.tree()["revision"] and promoted["contract_revision"])

    def test_entity_scope_mismatch_is_refused(self):
        memory = self.remember()
        node = self.core.create_node(name="other", entity_anchor="project z", status="active",
                                     evidence=["e1"])
        with self.assertRaises(CSMError) as caught:
            self.core.mount(memory["memory_id"], node_id=node["node_id"])
        self.assertEqual("tree_scope_entity_mismatch", str(caught.exception))


class WatermarkTests(DesignFixture):
    def test_since_reads_unconsumed_events_and_never_replays(self):
        pending = self.core.since("chat")
        self.assertEqual(3, len(pending["events"]))
        self.core.advance_watermark("chat", pending["events"][-1]["seq"])
        self.assertEqual([], self.core.since("chat")["events"])
        with self.assertRaises(CSMError):
            self.core.advance_watermark("chat", 0)

    def test_watermark_reports_available_sequence(self):
        marks = self.core.watermark()["watermarks"]
        self.assertEqual(0, marks[0]["last_seq"])
        self.assertEqual(3, marks[0]["available"])


class TimeTravelTests(DesignFixture):
    def test_valid_at_returns_the_revision_of_that_instant(self):
        self.remember()
        self.now = T2
        self.remember(value="Kubernetes 1.31", source_ids=("e3",))
        earlier = self.query(valid_at=T1)
        self.assertEqual("Kubernetes", earlier["results"][0]["value"])
        self.assertEqual("HISTORICAL", earlier["results"][0]["classification"])
        later = self.query(valid_at=T2)
        self.assertEqual("Kubernetes 1.31", later["results"][0]["value"])
        self.assertEqual("CURRENT_CONFIRMED", later["results"][0]["classification"])

    def test_valid_at_before_history_is_unknown_not_current(self):
        self.remember()
        result = self.query(valid_at="2026-10-01T00:00:00+00:00")
        self.assertEqual("UNKNOWN", result["results"][0]["classification"])
        self.assertEqual("valid_at_outside_history", result["results"][0]["reason"])
        self.assertNotIn("value", result["results"][0])

    def test_history_lists_superseded_revision(self):
        self.remember()
        self.now = T2
        self.remember(value="Kubernetes 1.31", source_ids=("e3",))
        result = self.query(include_history=True)
        superseded = [item for item in result["results"] if item["reason"] == "superseded"]
        self.assertEqual(1, len(superseded))
        self.assertEqual("Kubernetes", superseded[0]["value"])


class ProposalTests(DesignFixture):
    def test_unscoped_identity_gets_a_merge_proposal_that_must_be_applied(self):
        unscoped = self.remember(contexts=())
        scoped = self.remember()
        proposals = self.core.propose_identity_operations()
        self.assertEqual(1, len(proposals))
        self.assertEqual("identity_operation", proposals[0]["pending_type"])
        self.assertEqual(scoped["memory_id"], proposals[0]["memory_id"])
        self.assertEqual(unscoped["memory_id"], proposals[0]["source"])
        applied = self.core.apply_proposal(proposals[0]["pending_id"])
        self.assertEqual("MERGE", applied["operation"])
        read = self.core.memory(unscoped["memory_id"])
        self.assertEqual(scoped["memory_id"], read["identity"]["merged_into"])

    def test_ambiguous_proposal_is_not_applied(self):
        self.remember(contexts=(), value="Nomad")
        self.remember(contexts=("test",), value="Compose", source_ids=("e2",))
        self.remember(contexts=("staging",), value="Nomad", source_ids=("e3",))
        proposals = self.core.propose_identity_operations()
        incomplete = [item for item in proposals if item["missing_conditions"]]
        self.assertTrue(incomplete)
        with self.assertRaises(CSMError):
            self.core.apply_proposal(incomplete[0]["pending_id"])


if __name__ == "__main__":
    unittest.main()
