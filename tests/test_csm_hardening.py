"""Hardening of the retrieval path: filters before ranking, diversity, persisted index,
alias expansion, multi-hop reach, interval algebra and write-side digests.

Each behaviour is bypass-switched, so these tests set the flag they exercise and prove the
mechanism rather than the current default.
"""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery  # noqa: E402
from wsc.csm import digests, diversity, filters, index_store, relations, temporal  # noqa: E402

T1 = "2026-11-01T10:00:00+00:00"
T2 = "2026-11-02T10:00:00+00:00"
FLAGS = {"WSC_CSM_FILTERS": "1", "WSC_CSM_DIVERSITY": "1", "WSC_CSM_INDEX": "1",
         "WSC_CSM_ALIAS": "1", "WSC_CSM_MULTIHOP": "1", "WSC_CSM_EMBEDDER": "char",
         "WSC_CSM_RECALL": "hybrid"}


class IntervalTests(unittest.TestCase):
    def test_relation_and_clip_are_arithmetic(self):
        early = (temporal.moment("2026-01-01T00:00:00Z"), temporal.moment("2026-02-01T00:00:00Z"))
        late = (temporal.moment("2026-03-01T00:00:00Z"), None)
        overlap = (temporal.moment("2026-01-15T00:00:00Z"), temporal.moment("2026-03-15T00:00:00Z"))
        self.assertEqual(temporal.relation(early, late), "before")
        self.assertEqual(temporal.relation(early, overlap), "overlaps")
        self.assertTrue(temporal.intersects(early, overlap))
        self.assertFalse(temporal.intersects(early, late))
        clipped = temporal.clip(overlap, early)
        self.assertEqual(clipped, (temporal.moment("2026-01-15T00:00:00Z"),
                                   temporal.moment("2026-02-01T00:00:00Z")))
        self.assertEqual(temporal.duration(early), 31 * 86400.0)
        self.assertIsNone(temporal.duration(late))

    def test_unknown_endpoint_is_undecidable_not_empty(self):
        unknown = (None, None)
        known = (temporal.moment("2026-01-01T00:00:00Z"), None)
        self.assertIsNone(temporal.intersects(unknown, known))
        self.assertEqual(temporal.relation(unknown, known), "unknown")


class DiversityTests(unittest.TestCase):
    def test_mmr_trades_echoes_for_coverage(self):
        items = [{"value": "周六下午三点在旧书摊见阿岑", "score": 3.0},
                 {"value": "周六下午三点在旧书摊见阿岑。", "score": 2.9},
                 {"value": "阿岑换了手机号", "score": 2.0}]
        chosen = diversity.mmr(items, 2, lambda_=0.3)
        self.assertEqual(chosen[0]["value"], items[0]["value"])
        self.assertEqual(chosen[1]["value"], items[2]["value"])


class StateSemanticsTests(unittest.TestCase):
    def test_superseded_revision_is_historical(self):
        record = {"revision": 1, "status": "confirmed", "lifecycle": "open"}
        self.assertEqual(filters.classify(record, 2)[0], "HISTORICAL")
        self.assertEqual(filters.classify(record, 1)[0], "CURRENT_CONFIRMED")
        self.assertEqual(filters.classify({"revision": 1, "status": "rejected"}, 1)[0], "UNKNOWN")
        self.assertEqual(filters.classify({"revision": 1, "lifecycle": "closed"}, 1)[0],
                         "HISTORICAL")


class StoreCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = CSM(CsmStore(Path(directory.name) / "memory.db", namespace="user:lea"),
                        clock=lambda: T1)
        self.core.ingest([Event("e1", "chat", {"text": "许澄，小名小许，在青苔工作室"},
                                observed_at=T1),
                          Event("e2", "chat", {"text": "阿岑接替许澄负责账目"},
                                observed_at=T2)])
        self.written = self.core.remember([
            MemoryCandidate(entity="许澄", slot="公司", value="青苔工作室", source_ids=("e1",)),
            MemoryCandidate(entity="阿岑", slot="职责", value="负责账目", source_ids=("e2",))])

    def tearDown(self):
        index_store._CACHE.clear()


class FilteredIndexTests(StoreCase):
    def test_index_embeds_only_what_changed(self):
        with mock.patch.dict(os.environ, FLAGS):
            embedder = __import__("wsc.csm.cem.vector", fromlist=["vector"]).CharNgramEmbedder()
            with self.core.store.connect() as db:
                index = index_store.Index(db, embedder)
                with self.core.store.transaction() as db:
                    first = index_store.Index(db, embedder).sync(recorded_at=T1)
                    second = index_store.Index(db, embedder).sync(recorded_at=T2)
        self.assertEqual(first["embedded"], 2)
        self.assertEqual(second["embedded"], 0)
        self.assertEqual(second["reused"], 2)

    def test_entity_filter_runs_before_the_limit(self):
        with mock.patch.dict(os.environ, FLAGS):
            result = self.core.search("账目 工作室", limit=1)
            narrowed = __import__("wsc.csm.retrieval", fromlist=["retrieval"]).search(
                self._db(), "账目 工作室", limit=1, entities={"阿岑"})
        self.assertTrue(result["results"])
        self.assertEqual(narrowed["results"][0]["entity"], "阿岑")

    def _db(self):
        context = self.core.store.connect()
        db = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return db


class AliasTests(StoreCase):
    def test_confirmed_alias_makes_the_other_name_reachable(self):
        with mock.patch.dict(os.environ, FLAGS):
            self.core.confirm_alias("小许", "许澄", evidence=["e1"])
            found = self.core.query(MemoryQuery(entity="小许", slot="公司"))
        self.assertTrue(found["results"])
        self.assertEqual(found["results"][0]["entity"], "许澄")

    def test_proposals_need_evidence_and_write_nothing(self):
        with mock.patch.dict(os.environ, FLAGS):
            proposals = self.core.aliases()["proposals"]
        self.assertTrue(any(item["alias"] in ("小许", "许澄") for item in proposals))


class MultihopTests(StoreCase):
    def test_second_hop_keeps_the_edge_that_reached_it(self):
        first, second = self.written[0]["memory_id"], self.written[1]["memory_id"]
        self.core.link(kind="ASSOCIATION", subject=relations.memory_ref(second),
                       object=relations.memory_ref(first), evidence=("e2",), confirmed=True)
        with mock.patch.dict(os.environ, FLAGS):
            result = self.core.search("账目", limit=2, hops=2)
        reached = [item for item in result["results"]
                   if item.get("reason") == "multihop_neighbour"]
        self.assertTrue(reached)
        self.assertEqual(reached[0]["via"]["kind"], "ASSOCIATION")
        self.assertEqual(reached[0]["classification"], "UNKNOWN")


class DigestTests(StoreCase):
    def test_near_duplicate_observation_is_not_a_new_revision(self):
        head = self.core.memory(self.written[0]["memory_id"])["current"]["value"]
        self.assertTrue(digests.near_duplicate(head, head + "。"))
        self.assertFalse(digests.near_duplicate(head, "另一家工作室"))

    def test_compact_folds_history_without_rewriting_it(self):
        memory_id = self.written[0]["memory_id"]
        self.core.remember([MemoryCandidate(entity="许澄", slot="公司", value="苔原工作室",
                                            source_ids=("e2",), contexts=())])
        with mock.patch.dict(os.environ, FLAGS):
            folded = self.core.digest(memory_id)
        self.assertEqual(folded["through_revision"], 1)
        self.assertIn("青苔工作室", folded["digest"])
        self.assertEqual(self.core.memory(memory_id)["revision_count"], 2)


class RankingTests(StoreCase):
    def test_ties_break_on_identity_not_on_row_order(self):
        vector = __import__("wsc.csm.cem.vector", fromlist=["vector"])
        rows = [{"identity": {"memory_id": "m2"}}, {"identity": {"memory_id": "m1"}}]
        scores = [0.5, 0.5]
        first = vector._order(rows, scores, 2)
        second = vector._order(list(reversed(rows)), [0.5, 0.5], 2)
        self.assertEqual([rows[index]["identity"]["memory_id"] for index in first],
                         ["m1", "m2"])
        self.assertEqual([list(reversed(rows))[index]["identity"]["memory_id"]
                          for index in second], ["m1", "m2"])

    def test_cache_notices_an_in_place_revision(self):
        vector = __import__("wsc.csm.cem.vector", fromlist=["vector"])
        memory_id = self.written[0]["memory_id"]
        with mock.patch.dict(os.environ, {**FLAGS, "WSC_CSM_INDEX": "0"}):
            before = vector.search(self._db(), "青苔工作室", limit=3)
            self.core.remember([MemoryCandidate(entity="许澄", slot="公司", value="苔原工作室",
                                                source_ids=("e2",), contexts=())])
            after = vector.search(self._db(), "苔原工作室", limit=3)
        self.assertIn(memory_id, [item["memory_id"] for item in before["results"]])
        self.assertIn("苔原工作室", [item["value"] for item in after["results"]])

    def test_vector_mode_honours_anchors_without_the_index(self):
        vector = __import__("wsc.csm.cem.vector", fromlist=["vector"])
        with mock.patch.dict(os.environ, {**FLAGS, "WSC_CSM_RECALL": "vector",
                                          "WSC_CSM_INDEX": "0"}):
            widened = vector.search(self._db(), "工作室 账目", limit=5)
            narrowed = vector.search(self._db(), "工作室 账目", limit=5, entities={"阿岑"})
        self.assertGreater(len(widened["results"]), 1)
        self.assertEqual([item["entity"] for item in narrowed["results"]], ["阿岑"])

    def _db(self):
        context = self.core.store.connect()
        db = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return db


class WriteHookTests(StoreCase):
    def test_near_duplicate_write_does_not_add_a_revision(self):
        memory_id = self.written[0]["memory_id"]
        with mock.patch.dict(os.environ, {**FLAGS, "WSC_CSM_DIGEST": "1"}):
            again = self.core.remember([MemoryCandidate(entity="许澄", slot="公司",
                                                        value="青苔工作室。",
                                                        source_ids=("e1",), contexts=())])
        self.assertFalse(again[0]["changed"])
        self.assertEqual(again[0]["reason"], "near_duplicate_observation")
        self.assertEqual(self.core.memory(memory_id)["revision_count"], 1)

    def test_confirmed_alias_decides_where_a_write_lands(self):
        with mock.patch.dict(os.environ, {**FLAGS, "WSC_CSM_ALIAS": "1"}):
            self.core.confirm_alias("小许", "许澄", evidence=["e1"])
            written = self.core.remember([MemoryCandidate(entity="小许", slot="公司",
                                                          value="苔原工作室",
                                                          source_ids=("e2",), contexts=())])
        self.assertEqual(written[0]["memory_id"], self.written[0]["memory_id"])
        self.assertEqual(self.core.query(MemoryQuery(entity="许澄", slot="公司")
                                         )["results"][0]["value"], "苔原工作室")


if __name__ == "__main__":
    unittest.main()
