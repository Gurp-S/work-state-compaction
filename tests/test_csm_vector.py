"""Vector recall (§13.3): deterministic char embedder plus optional local ONNX model."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate  # noqa: E402
from wsc.csm import vector  # noqa: E402

MODEL_DIR = os.environ.get("WSC_CSM_EMBED_CACHE", r"E:\models\fastembed")
T1 = "2026-11-01T10:00:00+00:00"


class CharEmbedderTests(unittest.TestCase):
    def test_vectors_are_normalised_and_stable(self):
        embedder = vector.CharNgramEmbedder(dim=128)
        matrix = embedder.embed(["周六下午三点在旧书摊见阿岑", "周六下午三点在旧书摊见阿岑"])
        self.assertEqual(matrix.shape, (2, 128))
        self.assertAlmostEqual(float((matrix[0] ** 2).sum()), 1.0, places=5)
        self.assertTrue((matrix[0] == matrix[1]).all())


class VectorSearchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = CSM(CsmStore(Path(directory.name) / "memory.db", namespace="user:lea"),
                        clock=lambda: T1)
        self.core.ingest([Event("e1", "chat", {"text": "昨晚梦到舞台变成温室"},
                                observed_at=T1)])
        self.core.remember([
            MemoryCandidate(entity="用户", slot="梦境内容", value="昨晚梦到舞台变成一座温室",
                            source_ids=("e1",)),
            MemoryCandidate(entity="用户", slot="集合地点", value="周六下午三点在旧书摊",
                            source_ids=("e1",))])

    def tearDown(self):
        vector._EMBEDDER = None
        vector._CACHE.clear()

    def test_char_embedder_ranks_by_shared_characters(self):
        with mock.patch.dict(os.environ, {"WSC_CSM_RECALL": "vector",
                                          "WSC_CSM_EMBEDDER": "char"}):
            result = self.core.search("我昨晚梦到了什么？", limit=2)
        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["slot"], "梦境内容")
        self.assertEqual(result["results"][0]["reason"], "vector_match")

    @unittest.skipUnless(os.path.isdir(MODEL_DIR), "local embedding model not installed")
    def test_fastembed_semantic_recall(self):
        with mock.patch.dict(os.environ, {"WSC_CSM_RECALL": "vector",
                                          "WSC_CSM_EMBEDDER": "fastembed",
                                          "WSC_CSM_EMBED_CACHE": MODEL_DIR}):
            result = self.core.search("我梦见什么了？", limit=2)
        self.assertEqual(result["results"][0]["slot"], "梦境内容")
        self.assertGreater(result["results"][0]["score"], 0.4)

    def test_hybrid_keeps_exact_term_and_paraphrase(self):
        with mock.patch.dict(os.environ, {"WSC_CSM_RECALL": "hybrid",
                                          "WSC_CSM_EMBEDDER": "char"}):
            result = self.core.search("周六下午三点在旧书摊", limit=3)
        slots = [item["slot"] for item in result["results"]]
        self.assertEqual(slots[0], "集合地点")
        self.assertTrue(all(item["reason"] == "hybrid_match" for item in result["results"]))
        with mock.patch.dict(os.environ, {"WSC_CSM_RECALL": "hybrid",
                                          "WSC_CSM_EMBEDDER": "char"}):
            result = self.core.search("我梦到了什么？", limit=3)
        self.assertIn("梦境内容", [item["slot"] for item in result["results"]])


if __name__ == "__main__":
    unittest.main()
