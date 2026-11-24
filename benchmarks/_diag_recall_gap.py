"""Where the recall gap actually is: never stored, or stored but not retrieved.

A missing required clause in the top-15 has two very different causes, and they need opposite
fixes. If the clause is absent from the whole graph, extraction/representation never captured it
(write side). If it is present in the graph but absent from the top-15, ranking or fusion dropped
it (read side). This separates the two with no model calls, using the per-clause scores that
`csm_retrieval_eval.py` already wrote.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from csm_public_exam import load_answers, normalize  # noqa: E402
from csm_retrieval_eval import RESULTS, bigrams, gold_clauses  # noqa: E402
import read_exam  # noqa: E402

HIT = 0.9


def persona_texts(db_path: Path) -> dict[str, list[str]]:
    """Every stored memory, grouped by the persona whose turns produced it."""
    connection = sqlite3.connect(db_path)
    texts: dict[str, list[str]] = {}
    for (data,) in connection.execute("select data from projection"):
        record = json.loads(data)
        refs = " ".join(record.get("source_refs") or [])
        persona = refs.split("/")[0] if refs else ""
        text = normalize(f"{record.get('entity')} {record.get('slot')} {record.get('value')} "
                         f"{record.get('contexts') or ''}")
        texts.setdefault(persona, []).append(text)
    return texts


def best_recall(clause: str, texts: list[str]) -> float:
    target = bigrams(normalize(clause))
    if not target:
        return 0.0
    return max((len(target & bigrams(text)) / len(target) for text in texts), default=0.0)


def conversation_texts() -> dict[str, list[str]]:
    """The raw dialogue, so a clause absent from the graph can be traced to its cause."""
    _questions, histories = read_exam.load()
    texts: dict[str, list[str]] = {}
    for persona, payload in histories.items():
        turns = payload[0] if isinstance(payload, tuple) else payload
        texts[persona] = [normalize(f"{turn.get('用户消息')} {turn.get('助手回复')}")
                          for turn in turns]
    return texts


def main() -> None:
    arm = json.loads((RESULTS / "retrieval-lexical.json").read_text(encoding="utf-8"))
    answers = load_answers()
    corpus = persona_texts(RESULTS / "ab2-off.db")
    dialogue = conversation_texts()

    tally = {"hit": 0, "rank_miss": 0, "graph_miss": 0, "not_in_dialogue": 0}
    per_question = []
    for row in arm["rows"]:
        persona = row["id"].split("-")[0]
        texts = corpus.get(persona, [])
        spoken = dialogue.get(persona, [])
        statuses = []
        for clause, score in zip(row["clauses"], row["clause_scores"]):
            if score >= HIT:
                tally["hit"] += 1
                statuses.append("hit")
            elif best_recall(clause, texts) >= HIT:
                tally["rank_miss"] += 1
                statuses.append("rank_miss")
            elif best_recall(clause, spoken) >= HIT:
                tally["graph_miss"] += 1
                statuses.append("graph_miss")
            else:
                tally["not_in_dialogue"] += 1
                statuses.append("not_in_dialogue")
        per_question.append({"id": row["id"], "statuses": statuses,
                             "misses": [clause for clause, status in zip(row["clauses"], statuses)
                                        if status != "hit"]})

    total = sum(tally.values())
    print(f"clauses: {total}  " + "  ".join(f"{k}={v} ({v / total:.0%})" for k, v in tally.items()))
    bad = [q for q in per_question if q["misses"]]
    print(f"questions with a miss: {len(bad)}/{len(per_question)}")
    for status in ("graph_miss", "rank_miss", "not_in_dialogue"):
        print(f"  questions whose every miss is {status}: "
              f"{sum(1 for q in bad if q['statuses'].count(status) == len(q['misses']))}")

    (RESULTS / "recall-gap.json").write_text(json.dumps({"tally": tally, "questions": per_question},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
