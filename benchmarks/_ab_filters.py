"""Deterministic A/B over a real exam database: stale-revision leakage and state labels.

The public exam needs a live LLM judge, so this probe isolates the part that does not:
given the same questions and the same stored memories, does retrieval hand back superseded
revisions as if they were current? Run with the flags off and on; only the environment differs.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm import CsmStore  # noqa: E402
from wsc.csm import index_store, retrieval, state  # noqa: E402

DB = ROOT / "benchmarks" / "results" / "public-exam-hybrid.db"
QUESTIONS = ROOT / "benchmarks" / "results" / "public-exam-hybrid.json"


def run(label: str) -> dict:
    questions = [row["question"] for row in
                 json.loads(QUESTIONS.read_text(encoding="utf-8"))["results"]]
    store = CsmStore(DB, namespace="public-exam:PUB01")
    stale = current = total = 0
    timings = []
    with store.connect() as db:
        for question in questions:
            started = time.perf_counter()
            results = retrieval.search(db, question, limit=8)["results"]
            timings.append((time.perf_counter() - started) * 1000.0)
            for item in results:
                total += 1
                head = state.head(db, item.get("memory_id")) if item.get("memory_id") else None
                if head is not None and item.get("revision") != head["revision"]:
                    stale += 1
                if item.get("classification") == "CURRENT_CONFIRMED":
                    current += 1
    return {"arm": label, "questions": len(questions), "returned": total,
            "stale_share": round(stale / total, 4) if total else None,
            "current_share": round(current / total, 4) if total else None,
            "p50_ms": round(statistics.median(timings), 2),
            "p95_ms": round(sorted(timings)[int(0.95 * (len(timings) - 1))], 2)}


def main() -> None:
    flags = {"WSC_CSM_FILTERS": "1", "WSC_CSM_DIVERSITY": "1", "WSC_CSM_INDEX": "1",
             "WSC_CSM_ALIAS": "1", "WSC_CSM_MULTIHOP": "1"}
    base = {"WSC_CSM_RECALL": "hybrid", "WSC_CSM_EMBEDDER": "char"}
    off = {key: os.environ.pop(key, None) for key in flags}
    try:
        os.environ.update(base)
        print(json.dumps(run("off"), ensure_ascii=False))
        index_store._CACHE.clear()
        os.environ.update(flags)
        print(json.dumps(run("on"), ensure_ascii=False))
    finally:
        for key, value in off.items():
            if value is not None:
                os.environ[key] = value


if __name__ == "__main__":
    main()
