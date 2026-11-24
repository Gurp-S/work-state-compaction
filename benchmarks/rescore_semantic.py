"""语义级重新打分：用语义核对器判断 gold 要点是否被库里条目陈述，交叉 pass/fail。

    py -3.11 benchmarks/rescore_semantic.py --db benchmarks/results/ab2-off.db \
        --results benchmarks/results/public-exam-ab2-off.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

import attribution as A  # noqa: E402
from semantic_check import missing_clauses  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results" / "semantic_score.json")
    args = parser.parse_args()

    questions, _ = A.read_exam.load()
    answers = A.exam.load_answers()
    results = {r["id"]: r for r in json.loads(args.results.read_text(encoding="utf-8"))["results"]}
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = []
    for (data,) in con.execute("select data from projection"):
        payload = json.loads(data)
        rows.append(f"{payload.get('entity')} {payload.get('slot')} {payload.get('value')}")
    bigrams = [A.bigrams(row) for row in rows]

    chat = A.exam.Chat()
    table: dict[tuple[str, str], int] = {}
    details = []
    for index, question in enumerate(questions, 1):
        required = answers[question["id"]]["rubric"].get("required") or []
        if not required:
            continue
        clauses = [c for c in str(required[0]).split("；") if c.strip()]
        ranked = sorted(range(len(rows)),
                        key=lambda i: -max((A.covered(A.bigrams(c), bigrams[i]) for c in clauses), default=0))
        context = [rows[i] for i in ranked[:8]]
        gap = missing_clauses(chat, clauses, context)
        present = not gap
        passed = bool(results[question["id"]]["passed"])
        key = ("present" if present else "absent", "pass" if passed else "fail")
        table[key] = table.get(key, 0) + 1
        details.append({"id": question["id"], "present": present, "passed": passed, "gap": gap})
        if index % 20 == 0:
            print(f"{index} {table}", flush=True)

    args.out.write_text(json.dumps({"table": {f"{k[0]}|{k[1]}": v for k, v in table.items()},
                                    "details": details}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("final", table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
