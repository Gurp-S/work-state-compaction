"""Restatement admission and cross-process ranking stability."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wsc.csm import CSM, CSMError, CsmStore, Event, MemoryCandidate


class RepairBoundaryTests(unittest.TestCase):
    def test_digest_restatement_does_not_bypass_ambiguity_cas_or_type_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            core = CSM(CsmStore(Path(directory) / "m.db", namespace="repair"))
            core.ingest([Event("e", "chat", {"text": "部署成功"})])
            base = MemoryCandidate("system", "deployment", "部署成功", source_ids=("e",))
            memory_id = core.remember([base])[0]["memory_id"]
            with patch.dict(os.environ, {"WSC_CSM_DIGEST": "1"}):
                restated = core.remember([replace(base, value="部署成功。", topics=("deploy",))])[0]
                self.assertFalse(restated["changed"])
                self.assertEqual("near_duplicate_observation", restated["reason"])
                self.assertIn("deploy", core.memory(memory_id)["current"]["topics"])
                with self.assertRaisesRegex(CSMError, "memory_revision_conflict"):
                    core.remember([replace(base, value="部署成功。", expected_revision=2)])
                with self.assertRaisesRegex(CSMError, "semantic_type_conflict"):
                    core.remember([replace(base, semantic_type="Task")])
                denied = core.remember([replace(base, value="部署未成功")])[0]
                self.assertEqual("DEFER", denied["operation"])
                self.assertEqual("部署成功", core.memory(memory_id)["current"]["value"])
            with patch.dict(os.environ, {"WSC_CSM_DIGEST": "0"}):
                self.assertEqual("DEFER", core.remember([replace(base, value="部署成功。")])[0]["operation"])

    def test_final_evidence_packet_is_identical_across_hash_seeds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m.db"
            core = CSM(CsmStore(path, namespace="ranking"), clock=lambda: "2026-11-05T00:00:00Z")
            for index in range(25):
                text = " ".join("term" + str(n) for n in range(index + 1))
                source_id = "e" + str(index)
                core.ingest([Event(source_id, "chat", {"text": text})])
                core.remember([MemoryCandidate("entity" + str(index), "text", text,
                                               source_ids=(source_id,))])
            code = ("import json,sys; sys.path.insert(0," + repr(str(ROOT / "src")) + ");"
                    "from wsc.csm import CSM,CsmStore;"
                    "c=CSM(CsmStore(sys.argv[1],namespace='ranking'));"
                    "print(json.dumps(c.recall_evidence(' '.join('term'+str(i) for i in range(25))),"
                    "ensure_ascii=False,sort_keys=True))")
            outputs = []
            for seed in ("1", "2", "3", "17"):
                result = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(path)],
                                        env={**os.environ, "PYTHONHASHSEED": seed},
                                        capture_output=True, text=True, encoding="utf-8", check=True)
                outputs.append(json.loads(result.stdout))
            self.assertTrue(all(output == outputs[0] for output in outputs))
            self.assertTrue(outputs[0]["items"])


if __name__ == "__main__":
    unittest.main()
