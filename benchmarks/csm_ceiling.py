"""Ceiling experiment: what the score becomes when retrieval is perfect.

Two oracles, same answer prompt and same judge as the real exam, so the only thing that changes
is what the model is allowed to see:

    oracle-gold  the 15 stored memories that best match the rubric clauses (a perfect ranker)
    oracle-all   every memory stored before the question's cutoff (no retrieval at all)

Comparing them to the real 76/108 splits the loss into "retrieval dropped it" versus "the answer
or the judge is the limit".
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / ".bench" / "memory-system-benchmark" / "demo"))

import read_exam  # noqa: E402
from bench_llm import Chat  # noqa: E402
from csm_public_exam import ANSWER_SYSTEM, judge_llm, load_answers, normalize, render  # noqa: E402
from csm_retrieval_eval import RESULTS, bigrams, gold_clauses  # noqa: E402


def memories(db_path: Path) -> dict[str, list[dict]]:
    """Every stored memory with the persona and turn it came from."""
    connection = sqlite3.connect(db_path)
    by_persona: dict[str, list[dict]] = {}
    for (data,) in connection.execute("select data from projection"):
        record = json.loads(data)
        refs = " ".join(record.get("source_refs") or [])
        persona, _, tail = refs.partition("/turn/")
        if not tail.isdigit():
            continue
        record["_turn"] = int(tail)
        record["_text"] = normalize(f"{record.get('entity')} {record.get('slot')} "
                                    f"{record.get('value')} {record.get('contexts') or ''}")
        by_persona.setdefault(persona, []).append(record)
    for rows in by_persona.values():
        rows.sort(key=lambda row: row["_turn"])
    return by_persona


def overlap(clause: str, text: str) -> float:
    target = bigrams(normalize(clause))
    return len(target & bigrams(text)) / len(target) if target else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(RESULTS / "ab2-off.db"))
    parser.add_argument("--out", default=str(RESULTS / "ceiling.json"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    questions, _histories = read_exam.load()
    questions.sort(key=lambda q: (q["persona"], q["cutoff_turn"]))
    if args.limit:
        questions = questions[:args.limit]
    answers = load_answers()
    pool = memories(Path(args.db))
    chat = Chat()

    rows = []
    for question in questions:
        rubric = answers[question["id"]]["rubric"]
        clauses = gold_clauses(rubric)
        visible = [item for item in pool.get(question["persona"], [])
                   if item["_turn"] <= question["cutoff_turn"]]
        ranked = sorted(visible, key=lambda item: (-max((overlap(clause, item["_text"])
                                                         for clause in clauses), default=0.0),
                                                   -item["_turn"]))
        arms = {"oracle-gold": ranked[:15], "oracle-all": visible[-40:]}
        row = {"id": question["id"], "interval_days": answers[question["id"]]["interval_days"]}
        for name, items in arms.items():
            answer = chat.ask(ANSWER_SYSTEM, f"问题：{question['question']}\n记忆条目：{render(items)}",
                              max_tokens=200)
            passed, reason = judge_llm(chat, question["question"], answer, rubric)
            row[name] = {"passed": passed, "reason": reason, "answer": answer,
                         "context_size": len(items)}
        rows.append(row)
        done = len(rows)
        if done % 10 == 0:
            print(f"[{done}/{len(questions)}] " + " ".join(
                f"{name}={sum(1 for r in rows if r[name]['passed'])}" for name in arms), flush=True)

    summary = {"questions": len(rows)}
    for name in ("oracle-gold", "oracle-all"):
        summary[name] = {"passed": sum(1 for row in rows if row[name]["passed"]),
                         "accuracy": round(sum(1 for row in rows if row[name]["passed"]) / len(rows), 4)}
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False,
                                         indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
