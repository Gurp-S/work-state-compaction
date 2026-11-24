"""三步合一探针：
1) 28 道"gold 不在库且答错"的题，逐题给出 gold、最接近的库内条目、缺失二元组；
2) 校验 turn 32/41 是"真丢"还是"被后续修订覆盖"（查 revisions 里的来源引用）；
3) 按缺失类型归类，判断关系边是否是缺口。
输出：benchmarks/results/probe_gap.json（控制台只打印计数）
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))

import attribution as A  # noqa: E402

DB = ROOT / "benchmarks" / "results" / "ab2-off.db"
RES = ROOT / "benchmarks" / "results" / "public-exam-ab2-off.json"

COND = re.compile(r"还|之后|以后|才|如果|因为|所以|前|后|等到|顺路")
QUANT = re.compile(r"[0-9一二两三四五六七八九十半]|分钟|小时|点|天|周|月|年|次")
REL = re.compile(r"和|跟|与|陪|一起|帮|给")
NEG = re.compile(r"不|没|别|取消|作废")


def main() -> int:
    questions, _ = A.read_exam.load()
    answers = A.exam.load_answers()
    results = {r["id"]: r for r in json.loads(RES.read_text(encoding="utf-8"))["results"]}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = []
    for (data,) in con.execute("select data from projection"):
        d = json.loads(data)
        rows.append((str(d.get("entity", "")), str(d.get("slot", "")), str(d.get("value", ""))))

    gaps = []
    for question in questions:
        required = answers[question["id"]]["rubric"].get("required") or []
        if not required:
            continue
        gold = str(required[0])
        gold_bi = A.bigrams(gold)
        scored = sorted(((A.covered(gold_bi, A.bigrams(f"{e} {s} {v}")), e, s, v) for e, s, v in rows),
                        reverse=True)
        best = scored[0] if scored else (0.0, "", "", "")
        if best[0] >= 0.6 or results[question["id"]]["passed"]:
            continue
        best_bi = A.bigrams(f"{best[1]} {best[2]} {best[3]}")
        missing = sorted(gold_bi - best_bi)
        tags = [name for name, rx in (("cond", COND), ("quant", QUANT), ("rel", REL), ("neg", NEG))
                if rx.search(gold)]
        gaps.append({"id": question["id"], "coverage": round(best[0], 2), "gold": gold,
                     "best_value": best[3][:70], "missing": missing[:8], "tags": tags})

    # 第二步：turn 32/41 是真丢还是被覆盖
    refs = {}
    for turn in (32, 41, 52, 62, 71):
        event = f"PUB01/turn/{turn:04d}"
        refs[event] = {
            "revisions": con.execute("select count(*) from revisions where data like ?", (f"%{event}%",)).fetchone()[0],
            "projection": con.execute("select count(*) from projection where data like ?", (f"%{event}%",)).fetchone()[0],
        }

    counts = {"cond": 0, "quant": 0, "rel": 0, "neg": 0}
    for gap in gaps:
        for tag in gap["tags"]:
            counts[tag] += 1
    payload = {"gaps": gaps, "gap_count": len(gaps), "tag_counts": counts, "refs": refs}
    out = ROOT / "benchmarks" / "results" / "probe_gap.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("gaps", len(gaps), "tags", counts, "refs", refs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
