"""Deterministic reproductions from the WSC/CSM source review; no model calls."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CsmStore, CSMError, Event, MemoryCandidate, MemoryQuery
from wsc.csm import index_store, vector

T1 = "2026-11-01T10:00:00Z"
T2 = "2026-11-02T10:00:00Z"


class ReviewCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.env = mock.patch.dict(os.environ, {
            "WSC_CSM_RECALL": "vector", "WSC_CSM_EMBEDDER": "char",
            "WSC_CSM_INDEX": "0", "WSC_CSM_DIGEST": "0",
            "WSC_CSM_ALIAS": "0", "WSC_CSM_TREE": "0",
            "WSC_CSM_FILTERS": "0", "WSC_CSM_MULTIHOP": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        vector._EMBEDDER = vector.CharNgramEmbedder()
        vector._CACHE.clear()
        index_store._CACHE.clear()
        self.addCleanup(vector._CACHE.clear)
        self.addCleanup(index_store._CACHE.clear)
        self.addCleanup(setattr, vector, "_EMBEDDER", None)
        self.core = self.make_core("first")

    def make_core(self, name):
        core = CSM(CsmStore(self.directory / (name + ".db"), namespace=name),
                   clock=lambda: T2)
        core.ingest([Event("e1", "chat", {"text": "first"}, observed_at=T1),
                     Event("e2", "chat", {"text": "second"}, observed_at=T2)])
        return core

    def write(self, entity="project", slot="engine", value="alpha", core=None, **kw):
        return (core or self.core).remember([MemoryCandidate(
            entity=entity, slot=slot, value=value, source_ids=("e1",), **kw)])[0]

    def test_index_cache_does_not_cross_database_boundaries(self):
        os.environ["WSC_CSM_INDEX"] = "1"
        self.write(value="alpha")
        self.core.search("alpha")
        other = self.make_core("second")
        self.write(value="beta", core=other)
        found = other.search("beta")["results"]
        self.assertEqual([item["value"] for item in found], ["beta"])

    def test_vector_cache_notices_update_below_maximum_revision(self):
        self.write(entity="older", value="alpha")
        self.write(entity="older", value="alpha two", intent="update")
        self.write(entity="older", value="alpha three", intent="update")
        self.write(entity="newer", value="beta")
        self.core.search("beta")
        self.write(entity="newer", value="gamma", intent="update")
        found = self.core.search("gamma")["results"]
        self.assertEqual([item["value"] for item in found if item["entity"] == "newer"],
                         ["gamma"])

    def test_vector_cache_notices_merge_without_a_new_revision(self):
        kept = self.write(value="alpha", contexts=("prod",))
        retired = self.write(value="beta", contexts=("test",))
        self.core.search("beta")
        self.core.merge(kept["memory_id"], retired["memory_id"], evidence=["e2"])
        found = self.core.search("beta")["results"]
        self.assertNotIn(retired["memory_id"], [item["memory_id"] for item in found])

    def test_both_caches_notice_topic_enrichment(self):
        for indexed in ("0", "1"):
            with self.subTest(indexed=indexed):
                os.environ["WSC_CSM_INDEX"] = indexed
                core = self.make_core("topics" + indexed)
                written = self.write(core=core)
                core.search("alpha")
                core.enrich(written["memory_id"], topics=["zebra"])
                found = core.search("zebra")["results"]
                self.assertEqual([item["memory_id"] for item in found], [written["memory_id"]])

    def test_digest_keeps_domain_status_changes(self):
        self.write(semantic_type="Task", status="pending")
        os.environ["WSC_CSM_DIGEST"] = "1"
        changed = self.write(semantic_type="Task", status="running", intent="update")
        self.assertTrue(changed["changed"])
        self.assertEqual(self.core.memory(changed["memory_id"])["current"]["status"], "running")

    def test_digest_keeps_lifecycle_and_type_changes(self):
        self.write(semantic_type="Commitment")
        os.environ["WSC_CSM_DIGEST"] = "1"
        changed = self.write(semantic_type="Task", lifecycle="closed", intent="update")
        self.assertTrue(changed["changed"])
        current = self.core.memory(changed["memory_id"])["current"]
        self.assertEqual((current["semantic_type"], current["lifecycle"]), ("Task", "closed"))

    def test_digest_does_not_bypass_compare_and_swap(self):
        self.write()
        os.environ["WSC_CSM_DIGEST"] = "1"
        with self.assertRaisesRegex(CSMError, "memory_revision_conflict"):
            self.write(expected_revision=2)

    def test_digest_does_not_swallow_negation_or_version_changes(self):
        for first, second in (("部署成功", "部署未成功"), ("version 1.2", "version 12")):
            with self.subTest(first=first):
                self.write(slot=first, value=first)
                os.environ["WSC_CSM_DIGEST"] = "1"
                changed = self.write(slot=first, value=second, intent="update")
                self.assertTrue(changed["changed"])
                self.assertEqual(second, self.core.memory(changed["memory_id"])["current"]["value"])

    def test_digest_preserves_new_retrieval_topics(self):
        written = self.write()
        os.environ["WSC_CSM_DIGEST"] = "1"
        self.write(topics=("deployment",))
        result = self.core.query(MemoryQuery(topics=("deployment",)))
        self.assertEqual([item["memory_id"] for item in result["results"]],
                         [written["memory_id"]])

    def test_as_of_compares_timezone_offsets_as_instants(self):
        self.core.ingest([Event("offset", "chat", {},
                                observed_at="2026-11-01T11:00:00+02:00")])
        self.core.remember([MemoryCandidate("offset", "state", "known",
                                           source_ids=("offset",))])
        result = self.core.query(MemoryQuery(entity="offset", valid_at="2026-11-01T09:30:00Z"))
        self.assertEqual(result["results"][0]["value"], "known")

    def test_as_of_respects_explicit_valid_from(self):
        self.write(valid_from="2026-11-03T00:00:00Z")
        result = self.core.query(MemoryQuery(entity="project", valid_at=T2))
        self.assertFalse(any(item.get("confirmed") for item in result["results"]))

    def test_latest_evidence_uses_chronological_order(self):
        self.core.ingest([Event("offset", "chat", {},
                                observed_at="2026-11-01T11:00:00+02:00")])
        written = self.core.remember([MemoryCandidate("clock", "state", "known",
                                                      source_ids=("e1", "offset"))])[0]
        self.assertEqual(self.core.memory(written["memory_id"])["current"]["effective_at"], T1)


class StandardLibraryTests(unittest.TestCase):
    def test_default_lexical_search_needs_no_numpy(self):
        source = r'''
import importlib.abc, sys, tempfile
from pathlib import Path
class NoNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ModuleNotFoundError("optional numpy blocked")
sys.meta_path.insert(0, NoNumpy())
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate
with tempfile.TemporaryDirectory() as directory:
    core = CSM(CsmStore(Path(directory) / "memory.db", namespace="test"))
    core.ingest([Event("e1", "chat", {})])
    core.remember([MemoryCandidate("project", "engine", "alpha", source_ids=("e1",))])
    assert core.search("alpha")["results"][0]["value"] == "alpha"
'''
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
               "WSC_CSM_RECALL": "lexical", "WSC_CSM_MULTIHOP": "0"}
        completed = subprocess.run([sys.executable, "-S", "-c", source], env=env,
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
