"""CSM minimal slice: identity, versions, evidence, pending bindings, rebuild."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSCError
from wsc.csm import CSM, CSMError, CsmStore, Event, MemoryCandidate, MemoryQuery

CLOCK = "2026-11-02T00:00:00+00:00"


class CsmFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.core = CSM(CsmStore(self.root / "memory.db", namespace="user:lea"), clock=lambda: CLOCK)
        self.core.ingest([
            Event("e1", "chat", {"text": "prod deploys with k8s"}, observed_at="2026-11-01T10:00:00Z"),
            Event("e2", "chat", {"text": "test env deploys with compose"}, observed_at="2026-11-01T11:00:00Z"),
            Event("e3", "chat", {"text": "the deployment succeeded"}, observed_at="2026-11-01T12:00:00Z"),
        ])

    def candidate(self, **overrides):
        data = {"entity": "project a", "slot": "deployment engine", "value": "Kubernetes",
                "contexts": ("production",), "source_ids": ("e1",)}
        data.update(overrides)
        return MemoryCandidate(**data)

    def query(self, **overrides):
        data = {"entity": "project a", "slot": "deployment engine"}
        data.update(overrides)
        return self.core.query(MemoryQuery(**data))

    def classifications(self, result):
        return [(item["classification"], item.get("memory_id")) for item in result["results"]]


class IdentityTests(CsmFixture):
    def test_context_variants_are_separate_identities(self):
        production = self.core.remember([self.candidate()])[0]
        test = self.core.remember([self.candidate(value="Compose", contexts=("test",),
                                                  source_ids=("e2",))])[0]
        self.assertEqual("create", production["operation"])
        self.assertEqual("create", test["operation"])
        self.assertNotEqual(production["memory_id"], test["memory_id"])

        scoped = self.query(contexts=("production",))
        self.assertEqual([("CURRENT_CONFIRMED", production["memory_id"]),
                          ("UNKNOWN", test["memory_id"])],
                         self.classifications(scoped))
        self.assertEqual("Kubernetes", scoped["results"][0]["value"])

        unscoped = self.query()
        self.assertEqual(2, unscoped["counts"]["CURRENT_CONFIRMED"])

    def test_sibling_context_is_reported_unconfirmed(self):
        self.core.remember([self.candidate()])
        self.core.remember([self.candidate(value="Compose", contexts=("test",), source_ids=("e2",))])
        result = self.query(contexts=("staging",))
        self.assertEqual(2, result["counts"].get("UNKNOWN", 0))
        self.assertEqual(0, result["counts"].get("CURRENT_CONFIRMED", 0))
        self.assertTrue(all(item["reason"] == "context_mismatch" for item in result["results"]))

    def test_ambiguous_attribution_is_pending_until_anchored(self):
        production = self.core.remember([self.candidate()])[0]
        self.core.remember([self.candidate(value="Compose", contexts=("test",), source_ids=("e2",))])
        deferred = self.core.remember([self.candidate(value="succeeded", contexts=(),
                                                     source_ids=("e3",))])[0]
        self.assertEqual("DEFER", deferred["operation"])
        self.assertEqual(["context_anchor"], deferred["missing_conditions"])
        self.assertEqual(2, len(deferred["candidate_targets"]))

        before = self.query(contexts=("production",))
        self.assertEqual("Kubernetes", before["results"][0]["value"])
        self.assertEqual(1, before["counts"]["PENDING_BINDING"])

        resolved = self.core.resolve_pending(deferred["pending_id"], contexts=("production",))
        self.assertEqual("resolved", resolved["status"])
        self.assertEqual(production["memory_id"], resolved["memory_id"])
        self.assertEqual(2, resolved["revision"])
        self.assertEqual([], self.core.pending())
        after = self.query(contexts=("production",))
        self.assertEqual("succeeded", after["results"][0]["value"])

    def test_unresolvable_pending_stays_pending(self):
        self.core.remember([self.candidate()])
        self.core.remember([self.candidate(value="Compose", contexts=("test",), source_ids=("e2",))])
        deferred = self.core.remember([self.candidate(value="succeeded", contexts=(),
                                                     source_ids=("e3",))])[0]
        again = self.core.resolve_pending(deferred["pending_id"])
        self.assertEqual("pending", again["status"])
        self.assertEqual(1, len(self.core.pending()))


class RevisionTests(CsmFixture):
    def test_revision_appends_and_keeps_history(self):
        first = self.core.remember([self.candidate()])[0]
        second = self.core.remember([self.candidate(value="Nomad", source_ids=("e3",))])[0]
        self.assertEqual(1, first["revision"])
        self.assertEqual(2, second["revision"])
        memory = self.core.memory(first["memory_id"], history=True)
        self.assertEqual(2, memory["head_revision"])
        self.assertEqual(["Kubernetes", "Nomad"], [item["value"] for item in memory["history"]])
        self.assertEqual("Nomad", memory["current"]["value"])
        self.assertEqual(1, self.query()["counts"]["CURRENT_CONFIRMED"])
        historical = self.query(include_history=True)
        self.assertEqual(1, historical["counts"]["HISTORICAL"])
        self.assertEqual("Kubernetes", [item["value"] for item in historical["results"]
                                        if item["classification"] == "HISTORICAL"][0])

    def test_duplicate_observation_creates_no_revision(self):
        first = self.core.remember([self.candidate()])[0]
        again = self.core.remember([self.candidate()])[0]
        self.assertFalse(again["changed"])
        self.assertEqual(first["revision"], again["revision"])
        self.assertEqual(1, self.core.status()["revisions"])

    def test_stale_expected_revision_writes_nothing(self):
        self.core.remember([self.candidate()])
        with self.assertRaisesRegex(CSMError, "memory_revision_conflict"):
            self.core.remember([self.candidate(value="Nomad", source_ids=("e3",),
                                               expected_revision=5)])
        self.assertEqual(1, self.core.status()["revisions"])

    def test_type_narrowing_allowed_and_sideways_swap_rejected(self):
        commitment = self.core.remember([self.candidate(slot="migration", value="finish v2",
                                                        semantic_type="Commitment")])[0]
        narrowed = self.core.remember([self.candidate(slot="migration", value="finish v2",
                                                      semantic_type="Task", source_ids=("e3",))])[0]
        self.assertEqual("narrow", narrowed["operation"])
        self.assertEqual("Task", self.core.memory(commitment["memory_id"])["current"]["semantic_type"])
        with self.assertRaisesRegex(WSCError, "semantic_type_conflict"):
            self.core.remember([self.candidate(slot="migration", value="x",
                                               semantic_type="Preference", source_ids=("e3",))])
        # Narrowing is one-way: widening back would erase the guarantee it bought.
        with self.assertRaisesRegex(WSCError, "semantic_type_conflict"):
            self.core.remember([self.candidate(slot="migration", value="finish v2",
                                               semantic_type="Commitment", source_ids=("e3",))])


class EvidenceTests(CsmFixture):
    def test_unknown_source_is_rejected_without_writing(self):
        with self.assertRaisesRegex(WSCError, "evidence_source_unknown"):
            self.core.remember([self.candidate(source_ids=("missing",))])
        self.assertEqual(0, self.core.status()["identities"])

    def test_candidate_without_evidence_is_rejected(self):
        with self.assertRaisesRegex(WSCError, "evidence_source_missing"):
            self.core.remember([MemoryCandidate(entity="a", slot="b", value=1)])
        self.assertEqual(0, self.core.status()["revisions"])

    def test_event_ingest_is_idempotent_and_conflicts_are_detected(self):
        again = self.core.ingest([Event("e1", "chat", {"text": "prod deploys with k8s"})])
        self.assertEqual(["e1"], again["existing"])
        with self.assertRaisesRegex(WSCError, "event_conflict"):
            self.core.ingest([Event("e1", "chat", {"text": "different"})])
        self.assertEqual(3, self.core.status()["events"])


class RebuildTests(CsmFixture):
    def test_rebuild_restores_projection_and_head(self):
        memory = self.core.remember([self.candidate()])[0]
        self.core.remember([self.candidate(value="Nomad", source_ids=("e3",))])
        with self.core.store.transaction() as db:
            db.execute("UPDATE projection SET data = ? WHERE memory_id = ?",
                       (json.dumps({"value": "corrupted"}), memory["memory_id"]))
            db.execute("UPDATE heads SET current_revision = 99 WHERE memory_id = ?",
                       (memory["memory_id"],))
        report = self.core.rebuild()
        self.assertEqual(1, report["memories"])
        self.assertEqual(1, len(report["repaired_heads"]))
        self.assertEqual([memory["memory_id"]], report["rewritten"])
        current = self.core.memory(memory["memory_id"])["current"]
        self.assertEqual("Nomad", current["value"])
        self.assertEqual(2, current["revision"])
        self.assertEqual([], self.core.rebuild()["rewritten"])


class IdentityChangeTests(CsmFixture):
    """Rekey and merge: the declared context set is part of the identity key."""

    def test_rekey_declares_context_without_new_revision(self):
        created = self.core.remember([self.candidate(contexts=())])[0]
        self.assertEqual("project_a:deployment_engine", created["memory_id"])
        rekeyed = self.core.rekey(created["memory_id"], contexts=("production",),
                                  evidence=("e1",))
        self.assertEqual(["production"], rekeyed["contexts"])
        self.assertEqual([], rekeyed["previous_contexts"])
        self.assertEqual(created["memory_id"], rekeyed["memory_id"])

        result = self.query(contexts=("production",))
        self.assertEqual([("CURRENT_CONFIRMED", created["memory_id"])],
                         self.classifications(result))
        self.assertEqual(1, result["results"][0]["revision"])
        self.assertEqual(1, self.core.memory(created["memory_id"])["revision_count"])
        self.assertEqual(["rekey"], [item["kind"] for item in
                                     self.core.memory(created["memory_id"])["identity_changes"]])
        # New evidence at the same anchors lands on the rekeyed identity.
        self.assertEqual(created["memory_id"],
                         self.core.remember([self.candidate()])[0]["memory_id"])

    def test_rekey_requires_ingested_evidence(self):
        created = self.core.remember([self.candidate(contexts=())])[0]
        with self.assertRaisesRegex(CSMError, "identity_evidence_missing"):
            self.core.rekey(created["memory_id"], contexts=("production",), evidence=())
        
        with self.assertRaisesRegex(CSMError, "evidence_source_unknown"):
            self.core.rekey(created["memory_id"], contexts=("production",), evidence=("nope",))
        
        self.assertEqual([], self.core.memory(created["memory_id"])["identity"]["contexts"])

    def test_rekey_onto_existing_identity_is_rejected(self):
        vague = self.core.remember([self.candidate(contexts=())])[0]
        self.core.remember([self.candidate()])
        with self.assertRaisesRegex(CSMError, "identity_rekey_conflict"):
            self.core.rekey(vague["memory_id"], contexts=("production",), evidence=("e1",))
        

    def test_merge_retires_source_and_routes_new_evidence_to_target(self):
        vague = self.core.remember([self.candidate(contexts=())])[0]
        target = self.core.remember([self.candidate()])[0]
        with self.assertRaisesRegex(CSMError, "identity_evidence_missing"):
            self.core.merge(target["memory_id"], vague["memory_id"], evidence=())
        

        merged = self.core.merge(target["memory_id"], vague["memory_id"], evidence=("e1",))
        self.assertEqual(vague["memory_id"], merged["merged"])
        retired = self.core.memory(vague["memory_id"])
        self.assertEqual(target["memory_id"], retired["identity"]["merged_into"])
        self.assertEqual(1, retired["revision_count"])

        result = self.query()
        self.assertEqual([("CURRENT_CONFIRMED", target["memory_id"]),
                          ("HISTORICAL", vague["memory_id"])],
                         self.classifications(result))
        self.assertEqual("merged_into", result["results"][1]["reason"])
        # Evidence at the retired anchors now updates the live identity.
        routed = self.core.remember([self.candidate(contexts=(), value="Kubernetes 1.31",
                                                    source_ids=("e3",))])[0]
        self.assertEqual(target["memory_id"], routed["memory_id"])
        self.assertEqual(2, routed["revision"])

    def test_merge_requires_same_entity_and_slot(self):
        first = self.core.remember([self.candidate()])[0]
        other = self.core.remember([self.candidate(slot="deployment owner")])[0]
        with self.assertRaisesRegex(CSMError, "identity_merge_scope"):
            self.core.merge(first["memory_id"], other["memory_id"], evidence=("e1",))
        


    def test_merge_converges_survivor_anchor_in_one_transaction(self):
        vague = self.core.remember([self.candidate(contexts=())])[0]
        scoped = self.core.remember([self.candidate(contexts=("test",), value="Compose",
                                                    source_ids=("e3",))])[0]
        merged = self.core.merge(vague["memory_id"], scoped["memory_id"], evidence=("e1",),
                                 contexts=("production",))
        self.assertTrue(merged["converged"])
        self.assertEqual(["production"], merged["target_contexts"])

        survivor = self.core.memory(vague["memory_id"])
        self.assertEqual(["production"], survivor["identity"]["contexts"])
        self.assertEqual(1, survivor["revision_count"])
        self.assertEqual(["merge_in", "rekey"],
                         [item["kind"] for item in survivor["identity_changes"]])

        # The released anchor still routes to the survivor, and so does the new one.
        self.assertEqual([("CURRENT_CONFIRMED", vague["memory_id"]),
                          ("HISTORICAL", scoped["memory_id"])],
                         self.classifications(self.query(contexts=("production",))))
        routed = self.core.remember([self.candidate(contexts=("test",), value="Compose 2",
                                                    source_ids=("e3",))])[0]
        self.assertEqual(vague["memory_id"], routed["memory_id"])
        self.assertEqual(2, routed["revision"])

    def test_merge_convergence_conflict_rolls_retirement_back(self):
        vague = self.core.remember([self.candidate(contexts=())])[0]
        self.core.remember([self.candidate(contexts=("production",), value="Kubernetes",
                                           source_ids=("e1",))])
        scoped = self.core.remember([self.candidate(contexts=("test",), value="Compose",
                                                    source_ids=("e3",))])[0]
        with self.assertRaisesRegex(CSMError, "identity_rekey_conflict"):
            self.core.merge(vague["memory_id"], scoped["memory_id"], evidence=("e1",),
                            contexts=("production",))
        # Nothing half-applied: the source is still live and the survivor keeps its anchors.
        self.assertFalse(self.core.memory(scoped["memory_id"])["identity"].get("merged_into"))
        self.assertEqual([], self.core.memory(vague["memory_id"])["identity"]["contexts"])
        self.assertEqual([], self.core.memory(vague["memory_id"])["identity_changes"])
        self.assertEqual(3, len(self.query()["results"]))

    def test_merge_without_contexts_keeps_survivor_anchor(self):
        vague = self.core.remember([self.candidate(contexts=())])[0]
        scoped = self.core.remember([self.candidate(contexts=("test",), value="Compose",
                                                    source_ids=("e3",))])[0]
        merged = self.core.merge(vague["memory_id"], scoped["memory_id"], evidence=("e1",))
        self.assertFalse(merged["converged"])
        self.assertEqual([], merged["target_contexts"])
        self.assertEqual(["merge_in"], [item["kind"] for item in
                                     self.core.memory(vague["memory_id"])["identity_changes"]])


if __name__ == "__main__":
    unittest.main()
