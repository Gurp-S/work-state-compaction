"""Calibrate the retrieval metric against known end-to-end outcomes.

An exact-substring check undercounts paraphrases: the answer key allows synonyms, and the
model frequently answers a rubric clause without the clause appearing verbatim. Before trusting
any retrieval score, compare three candidates against the per-question pass/fail labels that
`public-exam-ab2-off.json` already recorded, and keep the one that separates them best.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from csm_retrieval_eval import ngram_recall  # noqa: E402
from wsc.csm.cem.vector import CharNgramEmbedder  # noqa: E402

RESULTS = ROOT / "benchmarks" / "results"


def cosine_coverage(clauses: list[str], texts: list[str], embedder) -> float:
    if not clauses or not texts:
        return 0.0
    gold = embedder.embed(clauses)
    context = embedder.embed(texts)
    scores = gold @ context.T
    return float(np.mean(scores.max(axis=1)))


def auc(scores: list[float], labels: list[bool]) -> float:
    positives = [s for s, y in zip(scores, labels) if y]
    negatives = [s for s, y in zip(scores, labels) if not y]
    if not positives or not negatives:
        return float("nan")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def main() -> None:
    arm = json.loads((RESULTS / "retrieval-lexical.json").read_text(encoding="utf-8"))
    exam = {row["id"]: row for row in
            json.loads((RESULTS / "public-exam-ab2-off.json").read_text(encoding="utf-8"))["results"]}
    embedder = CharNgramEmbedder()

    labels, exact, ngram, cosine = [], [], [], []
    for row in arm["rows"]:
        outcome = exam.get(row["id"])
        if outcome is None or "passed" not in outcome:
            continue
        labels.append(bool(outcome["passed"]))
        exact.append(row["coverage"])
        ngram.append(round(float(np.mean([ngram_recall(c, row["texts"]) for c in row["clauses"]])), 4)
                     if row["clauses"] else 0.0)
        cosine.append(round(cosine_coverage(row["clauses"], row["texts"], embedder), 4))

    print(f"questions with labels: {len(labels)}  passed: {sum(labels)}")
    for name, scores in (("exact-substring", exact), ("char-bigram", ngram), ("char-embedding", cosine)):
        passed = [s for s, y in zip(scores, labels) if y]
        failed = [s for s, y in zip(scores, labels) if not y]
        print(f"{name:16} mean_pass={np.mean(passed):.3f} mean_fail={np.mean(failed):.3f} "
              f"AUC={auc(scores, labels):.3f}")


if __name__ == "__main__":
    main()
