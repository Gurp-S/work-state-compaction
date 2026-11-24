"""Re-judge answers whose verdict fell back to the lexical rubric (invalid judge JSON)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from bench_llm import Chat  # noqa: E402
from csm_public_exam import judge_llm, load_answers  # noqa: E402


def main(path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data["results"]
    answers = load_answers()
    chat = Chat()
    fixed = 0
    for record in records:
        if not record.get("reason", "").startswith("lexical_fallback"):
            continue
        rubric = answers[record["id"]]["rubric"]
        passed, reason = judge_llm(chat, record["question"], record["answer"], rubric)
        record["passed"] = passed
        record["reason"] = reason
        fixed += 1
        print(("PASS " if passed else "FAIL ") + record["id"] + " " + reason[:60], flush=True)
    summary = data["summary"]
    summary["passed"] = sum(1 for record in records if record["passed"])
    summary["accuracy"] = round(summary["passed"] / len(records), 4)
    by_interval = {}
    for record in records:
        bucket = by_interval.setdefault(str(record["interval_days"]),
                                        {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if record["passed"] else 0
    summary["by_interval_days"] = by_interval
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("rejudged", fixed)


if __name__ == "__main__":
    main(sys.argv[1])

