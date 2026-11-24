"""Offline write-contract tests; attribution is supplied, never inferred."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CsmStore, CSMError, Event, MemoryCandidate, MemoryQuery


class ExplicitWriteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = CSM(CsmStore(Path(directory.name) / "test.db", namespace="explicit"),
                        clock=lambda: "2026-11-05T00:00:00Z")
        self.core.ingest([
            Event("base", "chat", {"text": "The stairway animal was white; two companions are A and B."}),
            Event("change", "chat", {"text": "The same animal is now grey. Companion C joined."}),
            Event("binding", "chat", {"text": "The animal on the steps refers to the stairway animal."}),
            Event("remove", "chat", {"text": "Companion A left."}),
        ])
        self.base = MemoryCandidate("stairway animal", "colour", "white", source_ids=("base",))
        self.memory_id = self.core.remember([self.base])[0]["memory_id"]
        self.change = MemoryCandidate("animal on the steps", "observed shade", "grey",
                                      source_ids=("change",), expected_revision=1)

    def write(self, candidate=None, **overrides):
        args = dict(operation="replace", target_memory_id=self.memory_id,
                    binding_source_ids=("binding",))
        args.update(overrides)
        return self.core.remember_explicit(candidate or self.change, **args)

    def head(self, memory_id=None):
        return self.core.memory(memory_id or self.memory_id)["current"]

    def snapshot(self):
        with self.core.store.connect() as db:
            return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
                    for table in ("identities", "revisions", "heads", "projection", "pending",
                                  "identity_changes", "memory_topics", "entity_aliases")}

    def test_per_write_mapping_replaces_target_without_global_alias_or_rekey(self):
        result = self.write()
        self.assertEqual(self.memory_id, result["memory_id"])
        self.assertEqual("grey", self.head()["value"])
        receipt = result["write_receipt"]
        self.assertEqual("animal on the steps", receipt["candidate"]["entity"])
        self.assertEqual("not_verified", receipt["semantic_support"])
        self.assertEqual(["change", "binding"], self.head()["source_refs"])
        with self.core.store.connect() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM identities").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM entity_aliases").fetchone()[0])
        self.assertEqual("white", self.core.memory(self.memory_id, history=True)["history"][0]["value"])

    def test_missing_attribution_or_cas_stays_pending_without_forking(self):
        for changes, missing in [({"target_memory_id": None}, "target_memory_id"),
                                  ({"binding_source_ids": ()}, "identity_binding_sources")]:
            result = self.write(**changes)
            self.assertEqual("DEFER", result["operation"])
            self.assertIn(missing, result["missing_conditions"])
        result = self.write(replace(self.change, expected_revision=None))
        self.assertIn("expected_revision", result["missing_conditions"])
        self.assertEqual("white", self.head()["value"])
        self.assertEqual(1, len(self.snapshot()["identities"]))

    def test_pending_requires_the_explicit_resolver_and_preserves_original(self):
        result = self.core.remember_explicit(replace(self.change, expected_revision=None))
        pending_id = result["pending_id"]
        with self.assertRaisesRegex(CSMError, "pending_type_mismatch"):
            self.core.resolve_pending(pending_id, operation="update")
        self.assertEqual("DEFER", self.core.resolve_explicit(pending_id)["operation"])
        settled = self.core.resolve_explicit(pending_id, operation="replace",
            target_memory_id=self.memory_id, binding_source_ids=("binding",), expected_revision=1)
        self.assertEqual(self.memory_id, settled["memory_id"])
        with self.assertRaisesRegex(CSMError, "pending_already_settled"):
            self.core.resolve_explicit(pending_id)

    def test_create_requires_a_distinct_declared_identity(self):
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, "create_identity_exists"):
            self.core.remember_explicit(replace(self.base, value="grey"), operation="create")
        self.assertEqual(before, self.snapshot())
        for context, value in [("observation:1", "white"), ("observation:2", "grey")]:
            self.core.remember_explicit(replace(self.base, value=value, contexts=(context,)),
                                        operation="create")
        self.assertEqual(3, len(self.snapshot()["identities"]))
        self.assertEqual("white", self.head()["value"])

    def test_observe_keeps_source_without_replacing_state(self):
        before = self.snapshot()
        result = self.core.remember_explicit(replace(self.change, expected_revision=None),
                                            operation="observe")
        self.assertEqual("OBSERVE", result["operation"])
        self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(CSMError, "observation_state_target_present"):
            self.write(operation="observe")

    def test_set_delta_preserves_base_members_sources_and_revision_history(self):
        base = MemoryCandidate("keeper", "companions", ["A", "B"], source_ids=("base",))
        memory_id = self.core.remember([base])[0]["memory_id"]
        delta = MemoryCandidate("C", "owner_species", ["C"], source_ids=("change",),
                                expected_revision=1)
        self.write(delta, operation="set_add", target_memory_id=memory_id)
        self.assertEqual(["A", "B", "C"], self.head(memory_id)["value"])
        self.assertEqual({"base", "change", "binding"}, set(self.head(memory_id)["source_refs"]))
        self.write(replace(delta, value=["A"], source_ids=("remove",), expected_revision=2),
                   operation="set_remove", target_memory_id=memory_id)
        self.assertEqual(["B", "C"], self.head(memory_id)["value"])
        self.core.rebuild()
        self.assertEqual(["B", "C"], self.head(memory_id)["value"])
        self.assertEqual(["A", "B"], self.core.memory(memory_id, history=True)["history"][0]["value"])

    def test_set_noops_and_typed_member_identity(self):
        base = replace(self.base, slot="set", value=[True, 1])
        memory_id = self.core.remember([base])[0]["memory_id"]
        delta = replace(base, value=[True], source_ids=("change",), expected_revision=1)
        result = self.write(delta, operation="set_add", target_memory_id=memory_id)
        self.assertFalse(result["changed"])
        self.write(delta, operation="set_remove", target_memory_id=memory_id)
        self.assertEqual([1], self.head(memory_id)["value"])
        self.assertIs(type(self.head(memory_id)["value"][0]), int)

    def test_invalid_set_shapes_fail_without_any_partial_write(self):
        for initial, delta, code in [("abc", ["a"], "collection_value_not_list"),
                                     ([1, 1], [2], "collection_duplicate_member"),
                                     ([1], [2, 2], "collection_duplicate_member")]:
            with self.subTest(initial=initial, delta=delta):
                created = self.core.remember([replace(self.base, slot=str(initial), value=initial)])[0]
                before = self.snapshot()
                with self.assertRaisesRegex(CSMError, code):
                    self.write(replace(self.change, value=delta), operation="set_add",
                               target_memory_id=created["memory_id"])
                self.assertEqual(before, self.snapshot())

    def test_stale_revision_cannot_publish_state_topics_or_receipt(self):
        self.write()
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, "memory_revision_conflict"):
            self.write(replace(self.change, topics=("new topic",)))
        self.assertEqual(before, self.snapshot())

    def test_unknown_or_corrupted_binding_source_cannot_publish(self):
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, "evidence_source_unknown"):
            self.write(binding_source_ids=("absent",))
        self.assertEqual(before, self.snapshot())
        with self.core.store.transaction() as db:
            db.execute("UPDATE events SET data = '{}' WHERE id = 'binding'")
        with self.assertRaisesRegex(CSMError, "evidence_source_digest_mismatch"):
            self.write()
        self.assertEqual("white", self.head()["value"])

    def test_type_and_domain_rules_precede_incomplete_binding(self):
        for candidate, code in [(replace(self.change, semantic_type="Task"), "semantic_type_conflict"),
                                 (replace(self.change, status="done"), "domain_status_unknown")]:
            before = self.snapshot()
            with self.assertRaisesRegex(CSMError, code):
                self.write(candidate, binding_source_ids=())
            self.assertEqual(before, self.snapshot())

    def test_pending_values_remain_unconfirmed_in_evidence_recall(self):
        self.core.remember_explicit(self.change)
        packet = self.core.recall_evidence("observed shade grey")
        pending_items = [r for r in packet["items"] if r["record_type"] == "pending"]
        self.assertTrue(pending_items)
        self.assertTrue(all(r["classification"] == "PENDING_BINDING" for r in pending_items))
        self.assertTrue(all(not r["confirmed"] for r in pending_items))
        anchored = self.core.query(MemoryQuery(entity="animal on the steps"))
        self.assertTrue(any(r.get("pending_type") == "explicit_write"
                            and not r["confirmed"] for r in anchored["results"]))

    def test_explicit_target_follows_an_existing_merge_without_new_aliases(self):
        scoped = self.core.remember([replace(self.base, contexts=("outside",))])[0]["memory_id"]
        self.core.merge(scoped, self.memory_id, evidence=("binding",))
        result = self.write()
        self.assertEqual(scoped, result["memory_id"])
        self.assertEqual("grey", self.head(scoped)["value"])

    def test_failed_pending_resolution_rolls_back_and_can_be_retried(self):
        result = self.core.remember_explicit(self.change)
        self.write()
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, "memory_revision_conflict"):
            self.core.resolve_explicit(result["pending_id"], operation="replace",
                target_memory_id=self.memory_id, binding_source_ids=("binding",))
        self.assertEqual(before, self.snapshot())
        settled = self.core.resolve_explicit(result["pending_id"], operation="replace",
            target_memory_id=self.memory_id, binding_source_ids=("binding",), expected_revision=2)
        self.assertEqual(self.memory_id, settled["memory_id"])


if __name__ == "__main__":
    unittest.main()
