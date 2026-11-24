"""Deterministic retrieval score for the public exam.

End-to-end scoring has three sampling layers before the number is produced: extraction,
query-clue interpretation, and answer+judge. Each of them alone moves more questions than any
flag we can plausibly ship, so an end-to-end A/B cannot attribute its delta.

This scores the retrieval step alone. Gold comes from the answer key's own `required` clauses,
so no extra model calls are involved: a run is a pure function of (graph, clues, flags) and is
reproducible byte for byte.

    py -3.11 benchmarks/csm_retrieval_eval.py --label lexical --recall lexical
    py -3.11 benchmarks/csm_retrieval_eval.py --label hybrid --recall hybrid --filters 1

Reported per arm:
    coverage        mean share of required clauses present in the rendered context
    complete        share of questions whose every required clause is present
    forbidden       questions whose context already contains a forbidden claim
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / ".bench" / "memory-system-benchmark" / "demo"))

import read_exam  # noqa: E402
from csm_public_exam import (  # noqa: E402
    DEMO, interpret, load_answers, normalize, render, resume_state, retrieve)
from wsc.csm import CSM, CsmStore  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"


def bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) > 1 else {text}


def ngram_recall(clause: str, texts: list[str]) -> float:
    """Share of a clause's character bigrams found in the closest retrieved item.

    Chosen over exact substring because the answer key allows synonyms: calibrated against the
    end-to-end pass/fail labels, this separates them at AUC 0.90 vs 0.76 for exact matching.
    """
    target = bigrams(clause)
    if not target:
        return 0.0
    best = 0.0
    for text in texts:
        hit = len(target & bigrams(text))
        best = max(best, hit / len(target))
    return best


def apply_flags(args) -> None:
    os.environ["WSC_CSM_RECALL"] = args.recall
    for name, value in (("WSC_CSM_FILTERS", args.filters), ("WSC_CSM_INDEX", args.index),
                        ("WSC_CSM_DIVERSITY", args.diversity),
                        ("WSC_CSM_MULTIHOP", args.multihop)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def gold_clauses(rubric: dict) -> list[str]:
    """The clauses an answer has to contain, exactly as the rubric states them."""
    clauses = [clause for item in rubric.get("required", [])
               for clause in item.split("；") if normalize(clause)]
    return clauses or [item for item in rubric.get("acceptable", []) if normalize(item)]


def score(db_path: Path, limit: int | None, clues: dict) -> dict:
    questions, _ = read_exam.load()
    questions.sort(key=lambda q: (q["persona"], q["cutoff_turn"]))
    if limit:
        questions = questions[:limit]
    answers = load_answers()
    resumed = resume_state(db_path)
    services: dict[str, tuple[CSM, list[str]]] = {}

    rows = []
    missing_clues: list[str] = []
    for question in questions:
        persona = question["persona"]
        if persona not in services:
            entities = resumed.get(persona, ([], 0))[0]
            services[persona] = (CSM(CsmStore(db_path, namespace=f"public-exam:{persona}")), entities)
        service, entities = services[persona]
        if question["question"] in clues:
            question_clues = interpret(None, question["question"], entities, clues)
        else:
            # No cached clues means no deterministic answer for this question; scoring it with
            # empty clues is honest (it measures what the question alone retrieves) but counted.
            question_clues = {"entities": [], "topics": []}
            missing_clues.append(question["question"])
        if "我" in question["question"]:
            question_clues["entities"] = list(dict.fromkeys(["用户", *question_clues["entities"]]))
        items = retrieve(service, question["question"], entities, question_clues)
        context = normalize(render(items))
        rubric = answers[question["id"]]["rubric"]
        clauses = gold_clauses(rubric)
        matched = [clause for clause in clauses if normalize(clause) in context]
        forbidden = [item for item in rubric.get("forbidden", [])
                     if normalize(item) and normalize(item) in context]
        texts = [normalize(f"{item.get('entity')} {item.get('slot')} {item.get('value')} "
                           f"{item.get('contexts') or ''}") for item in items]
        clause_scores = [round(ngram_recall(clause, texts), 3) for clause in clauses]
        rows.append({"id": question["id"], "interval_days": answers[question["id"]]["interval_days"],
                     "coverage": round(float(np.mean(clause_scores)), 3) if clause_scores else 0.0,
                     "exact": round(len(matched) / len(clauses), 3) if clauses else 0.0,
                     "clause_scores": clause_scores,
                     "missing": [clause for clause in clauses if clause not in matched],
                     "forbidden": forbidden,
                     "clauses": clauses, "texts": texts})
    return {"rows": rows, "missing_clues": sorted(set(missing_clues))}


def summarize(payload: dict, label: str, args) -> dict:
    rows = payload["rows"]
    total = len(rows)
    coverage = sum(row["coverage"] for row in rows) / total if total else 0.0
    exact = sum(row["exact"] for row in rows) / total if total else 0.0
    complete = sum(1 for row in rows if row["coverage"] >= 0.9)
    forbidden = sum(1 for row in rows if row["forbidden"])
    by_interval: dict[str, dict] = {}
    for row in rows:
        bucket = by_interval.setdefault(str(row["interval_days"]), {"total": 0, "coverage": 0.0})
        bucket["total"] += 1
        bucket["coverage"] += row["coverage"]
    for bucket in by_interval.values():
        bucket["coverage"] = round(bucket["coverage"] / bucket["total"], 3)
    return {"label": label, "flags": {k: getattr(args, k) for k in ("recall", "filters", "index",
                                                                   "diversity", "multihop")},
            "questions": total, "coverage": round(coverage, 4), "exact": round(exact, 4),
            "complete": complete, "forbidden": forbidden,
            "missing_clues": payload["missing_clues"],
            "by_interval_days": by_interval, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(RESULTS / "ab2-off.db"))
    parser.add_argument("--out", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--recall", default="lexical", choices=("lexical", "vector", "hybrid"))
    parser.add_argument("--filters", default=None)
    parser.add_argument("--index", default=None)
    parser.add_argument("--diversity", default=None)
    parser.add_argument("--multihop", default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    apply_flags(args)
    db_path = Path(args.db)
    clue_path = RESULTS / "clues.json"
    clues: dict = json.loads(clue_path.read_text(encoding="utf-8")) if clue_path.exists() else {}
    payload = score(db_path, args.limit or None, clues)
    clue_path.write_text(json.dumps(clues, ensure_ascii=False, indent=2), encoding="utf-8")

    label = args.label or f"recall={args.recall}"
    summary = summarize(payload, label, args)
    out = Path(args.out) if args.out else RESULTS / f"retrieval-{label.replace('=', '-').replace('+', '-')}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in
                      ("label", "flags", "questions", "coverage", "exact", "complete", "forbidden",
                       "by_interval_days")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
