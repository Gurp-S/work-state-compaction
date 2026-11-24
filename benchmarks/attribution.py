"""三段归因：一道题答错，是没写进库、写进去了没捞到，还是捞到了答错。

    py -3.11 benchmarks/attribution.py --db benchmarks/results/wsfix3.db \
        --results benchmarks/results/wsfix3-exam.json --out benchmarks/results/attr.json

不调用模型：写入层查库，检索层读跑批结果里的 retrieved 列表，生成层读 judge 结论。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csm_public_exam as exam  # noqa: E402
import read_exam  # noqa: E402

SPLIT = re.compile(r"[，、,;；。！？\s]+")


def bigrams(text: str) -> set[str]:
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def covered(gold: set[str], text: set[str]) -> float:
    """金标准字符二元组有多大比例出现在这段文字里；允许改写，不容忍丢内容。"""
    return len(gold & text) / len(gold) if gold else 0.0


def load_memories(db: Path) -> dict[str, dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out: dict[str, dict] = {}
    for memory_id, data in con.execute("select memory_id, data from projection"):
        row = json.loads(data if isinstance(data, str) else data.decode("utf-8"))
        row["memory_id"] = memory_id
        out[memory_id] = row
    con.close()
    return out


def text_of(row: dict) -> str:
    return f"{row.get('entity', '')}{row.get('slot', '')}{row.get('value', '')}"


def written(memories: dict[str, dict], gold: set[str], now: str | None,
            threshold: float = 0.6) -> list[str]:
    """库里在 now 之前就有、且覆盖了金标准阈值的记忆。"""
    if not gold:
        return []
    hits = []
    for memory_id, row in memories.items():
        effective = str(row.get("effective_at") or row.get("recorded_at") or "")
        if now and effective and effective[:19] > now[:19]:
            continue
        if covered(gold, bigrams(text_of(row))) >= threshold:
            hits.append(memory_id)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/attribution.json"))
    args = parser.parse_args()

    questions, _ = read_exam.load()
    answers = exam.load_answers()
    results = {row["id"]: row for row in json.loads(args.results.read_text(encoding="utf-8"))["results"]}
    memories = load_memories(args.db)

    buckets = {"not_written": [], "not_retrieved": [], "wrong_answer": [], "ok": []}
    rows = []
    for question in questions:
        qid = question["id"]
        if qid not in results:
            continue
        gold = bigrams(str(answers[qid]["rubric"]["required"][0])) if answers[qid]["rubric"].get("required") else set()
        hits = written(memories, gold, question.get("now"))
        retrieved = results[qid].get("retrieved") or []
        retrieved_hit = [mid for mid in retrieved if mid in hits]
        if not hits:
            bucket = "not_written"
        elif not retrieved_hit:
            bucket = "not_retrieved"
        elif not results[qid]["passed"]:
            bucket = "wrong_answer"
        else:
            bucket = "ok"
        buckets[bucket].append(qid)
        rows.append({"id": qid, "bucket": bucket, "written": len(hits),
                     "retrieved": len(retrieved), "retrieved_gold": len(retrieved_hit),
                     "passed": results[qid]["passed"]})

    total = sum(len(v) for v in buckets.values())
    summary = {name: {"count": len(ids), "share": round(len(ids) / total, 3) if total else 0}
               for name, ids in buckets.items()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"db": str(args.db), "results": str(args.results),
                                    "summary": summary, "rows": rows,
                                    "buckets": buckets}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"db={args.db.name} questions={total} memories={len(memories)}")
    for name in ("not_written", "not_retrieved", "wrong_answer", "ok"):
        print(f"  {name:<14} {len(buckets[name]):>3}  {summary[name]['share']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
