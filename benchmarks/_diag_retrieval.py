"""Retrieval-only diagnostic for the Locomo-Plus adapter.

Measures how often the gold answer appears in the retrieved memory text, without
spending any model calls. Run with WSC_CSM_RECALL=vector to compare recall paths.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm import CSM, CsmStore, MemoryQuery  # noqa: E402
from wsc.csm import retrieval  # noqa: E402

BENCH = ROOT / ".bench" / "Locomo-Plus"
DATA = BENCH / "data" / "locomo10.json"
DB = ROOT / "benchmarks" / "results" / "locomo-qa-conv0.db"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", str(text).lower()).strip()


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    sample = data[0]
    service = CSM(CsmStore(DB, namespace="locomo0"))
    total = hits = empty = 0
    per_category: dict[str, list[int]] = {}
    with service.store.connect() as db:
        for question in sample["qa"]:
            gold = norm(question.get("answer", ""))
            items = retrieval.search(db, question["question"], limit=12)["results"]
            text = norm(" ".join(str(item.get("value", "")) for item in items))
            found = bool(gold) and gold in text
            total += 1
            hits += found
            empty += not items
            bucket = per_category.setdefault(str(question.get("category")), [0, 0])
            bucket[0] += found
            bucket[1] += 1
    print(json.dumps({"questions": total, "gold_in_retrieved": hits,
                      "hit_rate": round(hits / total, 4), "empty_retrieval": empty,
                      "recall": os.environ.get("WSC_CSM_RECALL", "lexical"),
                      "by_category": {k: {"hits": v[0], "total": v[1]}
                                      for k, v in sorted(per_category.items())}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
