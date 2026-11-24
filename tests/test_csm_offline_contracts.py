"""Model-free regressions for loss metadata and bounded evidence selection."""
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import assembly, multihop
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery


def row(name, classification="CURRENT_CONFIRMED"):
    return {"memory_id": name, "value": name, "classification": classification,
            "source_refs": ["source/" + name]}


class AssemblyScopeTests(unittest.TestCase):
    def test_upstream_loss_survives_even_when_this_stage_fits(self):
        result = assembly.assemble({"results": [row("one")], "truncated": True})
        self.assertTrue(result["truncated"])
        self.assertEqual(result["omitted"], 0)

    def test_local_loss_and_upstream_loss_are_separate(self):
        result = assembly.assemble({"results": [row("one"), row("two")],
                                    "truncated": True}, max_items=1)
        self.assertTrue(result["upstream_truncated"])
        self.assertEqual(result["omitted"], 1)

    def test_no_loss_does_not_invent_loss(self):
        result = assembly.assemble({"results": [row("one")]})
        self.assertFalse(result["truncated"])


class HopBudgetTests(unittest.TestCase):
    def search(self, limit, diverse=False):
        direct = [row("direct/a"), row("direct/b"), row("direct/c")]
        related = row("related/a", "UNKNOWN")
        related.update(reason="multihop_neighbour",
                       via={"from": "direct/a", "rel_id": "edge/a"})
        with patch.object(multihop.retrieval, "search",
                          return_value={"results": direct, "counts": {"CURRENT_CONFIRMED": 3}}), \
                patch.object(multihop, "_neighbours", return_value=[related]):
            return multihop.explore(None, "question", limit=limit, hops=2, diverse=diverse)

    def test_full_direct_lane_does_not_erase_a_confirmed_edge_candidate(self):
        result = self.search(2)
        self.assertEqual([r["memory_id"] for r in result["results"]],
                         ["direct/a", "related/a"])
        self.assertEqual(result["results"][1]["classification"], "UNKNOWN")
        self.assertEqual(result["results"][1]["via"]["rel_id"], "edge/a")

    def test_limit_is_hard_and_counts_describe_returned_rows(self):
        for limit in (1, 2, 3, 4):
            with self.subTest(limit=limit):
                result = self.search(limit)
                self.assertLessEqual(len(result["results"]), limit)
                self.assertEqual(sum(result["counts"].values()), len(result["results"]))
                self.assertEqual(len({r["memory_id"] for r in result["results"]}),
                                 len(result["results"]))

    def test_dropped_candidates_are_reported(self):
        self.assertTrue(self.search(2)["truncated"])

    def test_diversity_does_not_reintroduce_hop_starvation(self):
        self.assertEqual([r["memory_id"] for r in self.search(2, diverse=True)["results"]],
                         ["direct/a", "related/a"])

    def test_single_hop_keeps_its_existing_order(self):
        direct = [row("direct/a"), row("direct/b")]
        with patch.object(multihop.retrieval, "search", return_value={"results": direct}), \
                patch.object(multihop, "_neighbours") as expand:
            result = multihop.explore(None, "question", limit=2, hops=1)
        self.assertEqual(result["results"], direct)
        expand.assert_not_called()

    def test_requested_scope_is_forwarded_and_checked_after_expansion(self):
        direct = {**row("direct/a"), "contexts": ["production"]}
        wrong = {**row("wrong", "UNKNOWN"), "reason": "multihop_neighbour",
                 "contexts": ["test"]}
        with patch.dict(os.environ, {"WSC_CSM_FILTERS": "1"}), \
                patch.object(multihop.retrieval, "search", return_value={"results": [direct]}) as search, \
                patch.object(multihop, "_neighbours", return_value=[wrong]):
            result = multihop.explore(None, "question", limit=2, contexts=("production",))
        self.assertEqual([r["memory_id"] for r in result["results"]], ["direct/a"])
        self.assertTrue(all(c.kwargs["contexts"] == ("production",) for c in search.call_args_list))


class PublicApiTests(unittest.TestCase):
    def test_query_truncation_reaches_public_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            core = CSM(CsmStore(Path(directory) / "memory.db", namespace="test"))
            core.ingest([Event("e", "chat", "source")])
            core.remember([MemoryCandidate("project", "property-" + str(i), i,
                                            source_ids=("e",)) for i in range(3)])
            output = core.assemble(MemoryQuery(entity="project", limit=1), max_items=10)
        self.assertEqual(len(output["items"]), 1)
        self.assertEqual(output["omitted"], 0)
        self.assertTrue(output["upstream_truncated"])
        self.assertTrue(output["truncated"])

    def test_full_lexical_hits_leave_room_for_real_graph_evidence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"WSC_CSM_MULTIHOP": "1", "WSC_CSM_RECALL": "lexical"}):
            core = CSM(CsmStore(Path(directory) / "memory.db", namespace="test"))
            core.ingest([Event("e", "chat", "source")])
            writes = core.remember([
                MemoryCandidate("project-" + str(i), "status", "deployment",
                                source_ids=("e",)) for i in range(3)])
            detail = core.remember([MemoryCandidate("detail", "reason", "permission absent",
                                                    source_ids=("e",))])[0]
            core.link(kind="ASSOCIATION", subject="memory:" + writes[0]["memory_id"],
                      object="memory:" + detail["memory_id"], evidence=("e",), confirmed=True)
            result = core.search("deployment", limit=2, hops=2)
        self.assertIn(detail["memory_id"], [r["memory_id"] for r in result["results"]])
        reached = next(r for r in result["results"] if r["memory_id"] == detail["memory_id"])
        self.assertEqual(reached["classification"], "UNKNOWN")
        self.assertTrue(reached["source_refs"])
        self.assertEqual(reached["via"]["kind"], "ASSOCIATION")


if __name__ == "__main__":
    unittest.main()
