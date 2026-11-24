"""抽取覆盖率探针：把原始抽取输出与原文逐句对照，区分"没被选择"与"过程丢失"。

用法：py -3.11 benchmarks/probe_coverage.py [--per-persona 3]
输出：benchmarks/results/probe_coverage.json（UTF-8，含原文、抽取行、掉落子句、库内行数）
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))
os.environ.setdefault("WSC_CSM_EXTRACT_FIX", "1")

import csm_public_exam as exam  # noqa: E402
from attribution import bigrams, covered  # noqa: E402

CUES = re.compile(r"还|之后|以后|因为|所以|如果|要是|顺便|除非|才|先|再|等|别|不能")
SPLIT = re.compile(r"[，。；！？、,.!?]")


def main() -> int:
    per = 3
    if "--per-persona" in sys.argv:
        per = int(sys.argv[sys.argv.index("--per-persona") + 1])

    chat = exam.Chat()
    questions, _ = exam.read_exam.load()
    by_hist: dict[str, str] = {}
    for question in questions:
        by_hist.setdefault(question["history_file"], question["persona"])

    db = sqlite3.connect(f"file:{ROOT / 'benchmarks' / 'results' / 'ab2-off.db'}?mode=ro", uri=True)
    records = []
    for hist, persona in by_hist.items():
        turns = [json.loads(line) for line in (exam.DEMO / hist).read_text(encoding="utf-8").splitlines() if line.strip()]
        picked = [t for t in turns if CUES.search(str(t.get("用户消息", "")))][:per]
        for turn in picked:
            rows = exam.extract(chat, turn, [])
            values = bigrams("\n".join(str(r["value"]) for r in rows))
            clauses = [c for c in SPLIT.split(str(turn.get("用户消息", ""))) if len(c) >= 4]
            dropped = [c for c in clauses if covered(bigrams(c), values) < 0.5]
            turn_no = int(turn.get("轮次") or 0)
            in_db = db.execute(
                "select count(*) from projection where data like ?",
                (f"%{persona}/turn/{turn_no:04d}%",),
            ).fetchone()[0]
            records.append({
                "persona": persona,
                "turn": turn_no,
                "user": turn.get("用户消息", ""),
                "assistant": turn.get("助手回复", ""),
                "extracted": [{"entity": r["entity"], "slot": r["slot"], "value": str(r["value"])} for r in rows],
                "clauses": clauses,
                "dropped": dropped,
                "db_rows": in_db,
            })

    out = ROOT / "benchmarks" / "results" / "probe_coverage.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print("turns", len(records),
          "extracted", sum(len(r["extracted"]) for r in records),
          "clauses", sum(len(r["clauses"]) for r in records),
          "dropped", sum(len(r["dropped"]) for r in records),
          "db_rows", sum(r["db_rows"] for r in records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
