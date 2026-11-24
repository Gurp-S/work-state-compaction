"""Side-by-side report for two CSM benchmark arms that share one extraction cache.

Usage:
    python benchmarks/compare_arms.py --base <dir> --opt <dir>
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import csm_census


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def rate(group: dict) -> str:
    return "; ".join(f"{name}: {value['passed']}/{value['total']}"
                     f"={value['passed'] / value['total']:.1%}"
                     for name, value in sorted(group.items()))


def arm(name: str, directory: Path) -> dict:
    summary = load(directory / "summary.json")
    answers = rows(directory / "answers.jsonl")
    latency = [row["retrieve_seconds"] for row in answers if "retrieve_seconds" in row]
    candidates = [row.get("candidates") for row in answers if row.get("candidates")]
    dbs = sorted(directory.glob("csm-*.db"))
    census = [csm_census.census(path) for path in dbs]
    return {
        "name": name,
        "directory": str(directory),
        "score": f"{summary['passed']}/{summary['scored']} = "
                 f"{summary['passed'] / summary['scored']:.1%}",
        "persona": rate(summary["groups"]["persona"]),
        "interval": rate(summary["groups"]["interval_days"]),
        "content_tags": rate(summary["groups"]["content_tags"]),
        "answers": len(answers),
        "errors": sum(1 for row in answers if row.get("error")),
        "retrieve_median": round(statistics.median(latency), 3) if latency else None,
        "retrieve_p95": (round(sorted(latency)[int(len(latency) * 0.95)], 3)
                         if latency else None),
        "candidates_median": round(statistics.median(candidates), 1) if candidates else None,
        "census": census,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--opt", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = [arm("baseline", args.base), arm("optimized", args.opt)]
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
