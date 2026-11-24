"""Compare graded CSM arms on all scored questions and on the common valid subset.

    python benchmarks/cmb1_compare.py --arm base=benchmarks/results/cmb1-base-20261118 \
        --arm opt=benchmarks/results/cmb1-opt-20261118 --arm core=benchmarks/results/cmb1-core-20261118
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_arm(name: str, directory: Path) -> dict:
    answers = {row["id"]: row for row in rows(directory / "answers.jsonl")}
    verdicts = {row["id"]: row for row in rows(directory / "judgments.jsonl")}
    failed = {ident for ident, row in answers.items() if row.get("error")}
    latency = [row["retrieve_seconds"] for row in answers.values()
               if isinstance(row.get("retrieve_seconds"), (int, float))]
    candidates = [row["candidates"] for row in answers.values()
                  if isinstance(row.get("candidates"), int)]
    return {"name": name, "directory": str(directory), "answers": answers,
            "verdicts": verdicts, "failed": failed,
            "latency": latency, "candidates": candidates}


def rate(passed: int, total: int) -> dict:
    return {"passed": passed, "total": total,
            "rate": round(passed / total, 4) if total else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", action="append", required=True,
                        help="name=directory; repeat for each arm")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    arms = []
    for spec in args.arm:
        name, _, directory = spec.partition("=")
        arms.append(load_arm(name, Path(directory)))
    valid = {arm["name"]: set(arm["verdicts"]) - arm["failed"] for arm in arms}
    common = set.intersection(*valid.values()) if valid else set()
    report = []
    for arm in arms:
        all_rows = arm["verdicts"].values()
        own_valid = valid[arm["name"]]
        report.append({
            "arm": arm["name"],
            "judged": len(arm["verdicts"]),
            "failed_gateway": len(arm["failed"]),
            "valid": rate(sum(1 for ident in own_valid if arm["verdicts"][ident]["pass"]),
                          len(own_valid)),
            "common_valid": rate(
                sum(1 for ident in common if arm["verdicts"].get(ident, {}).get("pass")),
                len(common)),
            "all_judged": rate(sum(1 for row in all_rows if row["pass"]), len(arm["verdicts"])),
            "retrieve_median": (round(statistics.median(arm["latency"]), 3)
                                if arm["latency"] else None),
            "retrieve_p95": (round(sorted(arm["latency"])[int(len(arm["latency"]) * 0.95)], 3)
                             if arm["latency"] else None),
            "candidates_median": (round(statistics.median(arm["candidates"]), 1)
                                  if arm["candidates"] else None),
            "by_persona": {
                persona: rate(
                    sum(1 for ident in common if arm["verdicts"].get(ident, {}).get("persona") == persona
                        and arm["verdicts"][ident]["pass"]),
                    sum(1 for ident in common if arm["verdicts"].get(ident, {}).get("persona") == persona))
                for persona in sorted({row.get("persona") for row in arm["verdicts"].values()})},
        })
    text = json.dumps({"common_ids": len(common), "arms": report}, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
