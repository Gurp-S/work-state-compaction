"""Does the anchor-filter flag change the retrieved set, with query clues held fixed?

Runs the exam's own retrieve() twice per question on one fixed graph — filters off and on —
using a single shared clue cache, so the only variable is WSC_CSM_FILTERS.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / ".bench" / "memory-system-benchmark" / "demo"))

import read_exam  # noqa: E402
from bench_llm import Chat  # noqa: E402
from csm_public_exam import interpret, resume_state, retrieve  # noqa: E402
from wsc.csm import CSM, CsmStore  # noqa: E402

RESULTS = ROOT / "results"


def main() -> None:
    questions, _ = read_exam.load()
    questions.sort(key=lambda q: (q["persona"], q["cutoff_turn"]))
    db_path = RESULTS / "ab2-off.db"
    resumed = resume_state(db_path)
    entities, _turns = resumed["PUB01"]
    service = CSM(CsmStore(db_path, namespace="public-exam:PUB01"))

    clue_path = RESULTS / "clues.json"
    cache = json.loads(clue_path.read_text(encoding="utf-8")) if clue_path.exists() else {}
    chat = Chat()

    differing, compared = [], 0
    for question in questions:
        clues = interpret(chat, question["question"], entities, cache)
        if "我" in question["question"]:
            clues["entities"] = list(dict.fromkeys(["用户", *clues["entities"]]))
        sets = {}
        for label, flag in (("off", "0"), ("on", "1")):
            os.environ["WSC_CSM_RECALL"] = "hybrid"
            os.environ["WSC_CSM_FILTERS"] = flag
            os.environ.pop("WSC_CSM_INDEX", None)
            sets[label] = [item["memory_id"] for item in
                           retrieve(service, question["question"], entities, clues)]
        compared += 1
        if sets["off"] != sets["on"]:
            differing.append((question["id"], len(set(sets["off"]) & set(sets["on"]))))
        if compared % 20 == 0:
            clue_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{compared}/{len(questions)}] differing so far: {len(differing)}", flush=True)

    clue_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"compared {compared}, retrieved sets differing: {len(differing)}")
    for row in differing[:10]:
        print("  ", row)


if __name__ == "__main__":
    main()
