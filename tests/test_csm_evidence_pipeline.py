"""Engine and real-adapter contracts; no model or external service involved."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery, CSMError
from wsc.csm.cem.recall_terms import terms


class EvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = CSM(CsmStore(Path(self.temp.name) / "memory.db", namespace="test"))
        self.core.ingest([Event("e1", "chat", {"user": "Two independent observations: blue wall and wooden floor.",
                                              "assistant": "Recorded."}, observed_at="2026-01-01T00:00:00Z"),
                          Event("e2", "chat", {"user": "Later observation."}, observed_at="2026-02-01T00:00:00Z")])

    def candidate(self, value, **kw):
        return MemoryCandidate("room", "description", value, source_ids=(kw.pop("source", "e1"),), **kw)

    def test_eligible_lane_gets_budget_before_state_or_duplicate_rows(self):
        self.core.remember([self.candidate("blue wall")])
        before = self.core.recall_evidence("room blue wall", limit=1)
        self.assertEqual(before["items"][0]["record_type"], "memory")
        packet = self.core.recall_evidence("room blue wall", limit=1, record_types=("source_event",))
        self.assertEqual(len(packet["items"]), 1)
        self.assertEqual(packet["items"][0]["record_type"], "source_event")
        excluded = packet["items"][0]["memory_id"]
        packet = self.core.recall_evidence("observation", limit=1,
            record_types=("source_event",), exclude_ids=(excluded,))
        self.assertEqual(len(packet["items"]), 1)
        self.assertNotEqual(packet["items"][0]["memory_id"], excluded)
        self.assertEqual(packet["used_chars"], len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))))
        with self.assertRaises(CSMError):
            self.core.recall_evidence("blue", record_types="source_event")
        with self.assertRaises(CSMError):
            self.core.recall_evidence("blue", record_types=[[]])

    def test_implicit_same_event_values_stay_pending_without_overwrite(self):
        result = self.core.remember([self.candidate("blue wall"), self.candidate("wooden floor")])
        self.assertTrue(all(r["operation"] == "DEFER" for r in result))
        self.assertEqual({p["semantic_payload"]["value"] for p in self.core.pending()},
                         {"blue wall", "wooden floor"})
        self.assertFalse(any(r["classification"] == "CURRENT_CONFIRMED" for r in
                             self.core.query(MemoryQuery(entity="room"))["results"]))

    def test_explicit_updates_and_different_events_keep_normal_versioning(self):
        self.core.remember([self.candidate("old")])
        self.core.remember([self.candidate("new", source="e2")])
        self.core.remember([self.candidate("explicit-a", source="e2", intent="update"),
                            self.candidate("explicit-b", source="e2", intent="update")])
        self.assertEqual(self.core.query(MemoryQuery(entity="room"))["results"][0]["value"], "explicit-b")

    def test_duplicate_observations_are_not_ambiguous(self):
        result = self.core.remember([self.candidate("same"), self.candidate("same")])
        self.assertTrue(all(r["operation"] != "DEFER" for r in result))

    def test_separate_calls_cannot_bypass_the_same_source_guard(self):
        self.core.remember([self.candidate("blue wall")])
        second = self.core.remember([self.candidate("wooden floor")])[0]
        self.assertEqual(second["operation"], "DEFER")
        still_pending = self.core.resolve_pending(second["pending_id"])
        self.assertEqual(still_pending["status"], "pending")
        self.assertEqual(self.core.query(MemoryQuery(entity="room"))["results"][0]["value"], "blue wall")

    def test_source_expansion_is_bounded_evidence_not_an_identity_merge(self):
        self.core.ingest([Event("anchor", "chat", {"user": "anchor cobalt walnut"}),
                          Event("related", "chat", {"user": "cobalt walnut continuation"})]
                         + [Event("noise-" + str(i), "chat", {"user": "unrelated filler " + str(i)})
                            for i in range(60)])
        packet = self.core.recall_evidence("anchor", limit=2)
        related = next(r for r in packet["items"] if r["source_refs"] == ["related"])
        self.assertEqual(related["classification"], "UNKNOWN")
        self.assertEqual(related["retrieval_via"]["reason"], "literal_source_overlap")
        self.assertEqual(len(packet["items"]), 2)
        with self.core.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM relations").fetchone()[0], 0)

    def test_groups_use_the_same_ambiguity_guard(self):
        result = self.core.remember_group([self.candidate("a"), self.candidate("b")], group_id="g1")
        self.assertEqual(result["group"]["status"], "deferred")

    def test_sources_survive_even_when_state_interpretation_is_pending(self):
        self.core.remember([self.candidate("blue wall"), self.candidate("wooden floor")])
        packet = self.core.recall_evidence("wall floor", limit=8)
        source = next(r for r in packet["items"] if r.get("record_type") == "source_event")
        self.assertEqual(source["value"]["user"], "Two independent observations: blue wall and wooden floor.")
        self.assertEqual(source["classification"], "UNKNOWN")
        self.assertEqual(source["evidence"], ["e1"])
        self.assertEqual(packet["completeness"], "not_established")

    def test_time_scope_excludes_future_sources(self):
        packet = self.core.recall_evidence("observation", until="2026-01-15T00:00:00Z")
        self.assertTrue(all("e2" not in r["evidence"] for r in packet["items"]))

    def test_surface_normalization_does_not_change_identity_or_source(self):
        self.assertEqual(terms("paint painted painting paints"), {"paint"})
        self.assertEqual(terms("book books read reading reads"), {"book", "read"})
        self.assertIn("not", terms("not painted"))

    def test_dialogue_context_keeps_speakers_and_ids_out_of_ranking(self):
        self.core.ingest([Event("dialogue", "chat", {"date": "PROVENANCE_ONLY",
            "turns": [{"dia_id": "ANCHOR_METADATA", "speaker": "A", "text": "Which instrument?"},
                      {"dia_id": "reply", "speaker": "B", "text": "A clarinet."}]})])
        packet = self.core.recall_evidence("clarinet", limit=2)
        source = next(r for r in packet["items"] if r.get("record_type") == "source_event")
        self.assertEqual([t["speaker"] for t in source["value"]["turns"]], ["A", "B"])
        self.assertEqual(source["classification"], "UNKNOWN")
        metadata_only = self.core.recall_evidence("ANCHOR_METADATA PROVENANCE_ONLY", limit=2)
        self.assertFalse(metadata_only["items"])

    def test_serialized_packet_has_a_hard_budget(self):
        packet = self.core.recall_evidence("observation wall", limit=1, max_chars=1400)
        self.assertLessEqual(len(packet["items"]), 1)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))), 1400)

    def test_corrupted_source_is_not_returned_as_evidence(self):
        # A warmed lexical cache must never bypass a later source digest check.
        self.core.recall_evidence("wall")
        with self.core.store.transaction() as db:
            db.execute("UPDATE events SET data=? WHERE id=?", ('{"user":"tampered"}', "e1"))
        with self.assertRaisesRegex(CSMError, "evidence_source_digest_mismatch"):
            self.core.recall_evidence("tampered")

    def test_real_adapter_keeps_packet_metadata_and_source_attribution(self):
        import csm_public_exam as adapter
        with patch.dict(os.environ, {"WSC_CSM_EVIDENCE_PIPELINE": "1"}):
            rows = adapter.retrieve(self.core, "wall floor", [], {"entities": [], "topics": []})
        rendered = json.loads(adapter.render(rows))
        self.assertEqual(rendered["policy"], adapter.evidence_adapter.POLICY)
        self.assertIn("completeness", rendered)
        self.assertTrue(any(r.get("record_type") == "source_event" for r in rendered["items"]))

    def test_incidental_chinese_question_words_do_not_admit_unrelated_chat(self):
        self.core.ingest([Event("topic", "chat", {"user": "设备的保修期限为两年。"}),
                          Event("incidental", "chat", {"user": "我想吃酸的。", "assistant": "家里有什么现成的？"})])
        rows = self.core.recall_evidence("我问过设备的保修期限是什么？")["items"]
        self.assertTrue(any("topic" in r["source_refs"] for r in rows))
        self.assertFalse(any("incidental" in r["source_refs"] for r in rows))

    def test_character_fallback_still_recovers_a_floor_number(self):
        self.core.ingest([Event("floor", "chat", {"user": "我住四楼。"}),
                          Event("generic", "chat", {"user": "说过自己要休息。"})])
        for question in ("住几楼？", "我说过自己住几楼？"):
            rows = self.core.recall_evidence(question)["items"]
            self.assertTrue(any("floor" in r["source_refs"] for r in rows))

    def test_identity_head_does_not_certify_current_world_state(self):
        self.core.remember([self.candidate("blue wall")])
        legacy = self.core.query(MemoryQuery(entity="room"))["results"]
        self.assertEqual(legacy[0]["classification"], "CURRENT_CONFIRMED")
        packet = self.core.recall_evidence("blue wall")
        memory = next(r for r in packet["items"] if r.get("record_type") == "memory")
        self.assertEqual(memory["classification"], "UNKNOWN")
        self.assertEqual(memory["identity_classification"], "CURRENT_CONFIRMED")
        self.assertFalse(memory["confirmed"])
        self.assertIn("not_world_confirmation", packet["state_scope"])

    def test_dialogue_projection_retains_original_media_fields(self):
        turn = {"dia_id": "photo", "speaker": "A", "text": "Look at this sign.",
                "blip_caption": "a sign saying library closed", "img_url": ["https://example.test/image"],
                "query": "UNVERIFIED_SEARCH_HINT", "custom": {"origin": "dataset"}}
        self.core.ingest([Event("media", "chat", {"date": "2026", "turns": [turn]})])
        packet = self.core.recall_evidence("library closed")
        source = next(r for r in packet["items"] if r.get("record_type") == "source_event")
        self.assertEqual(source["value"]["turns"][0], turn)
        self.assertEqual(source["classification"], "UNKNOWN")
        self.assertFalse(self.core.recall_evidence("UNVERIFIED_SEARCH_HINT")["items"])

    def test_media_only_turn_is_not_silently_dropped(self):
        turn = {"dia_id": "image-only", "speaker": "A", "img_url": ["https://example.test/sign"],
                "blip_caption": "a handwritten observatory schedule"}
        self.core.ingest([Event("image-only", "chat", {"date": "2026", "turns": [turn]})])
        packet = self.core.recall_evidence("observatory schedule")
        source = next(r for r in packet["items"] if r.get("record_type") == "source_event")
        self.assertEqual(source["value"]["turns"], [turn])


if __name__ == "__main__":
    unittest.main()
