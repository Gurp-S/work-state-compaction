"""Diversity control (MMR): a retrieval set should cover distinct facts, not echoes.

Plain top-k returns five phrasings of one memory and nothing about the other three things
the caller asked. Maximal Marginal Relevance picks each next item for relevance minus its
similarity to what is already chosen, so the budget buys coverage instead of repetition.
Similarity is token Jaccard: it works for lexical and vector candidates alike and needs no
extra embedding call.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def tokens(text) -> set:
    """Latin words plus CJK bigrams, matching the retrieval tokenizer's granularity."""
    out = set()
    for chunk in _WORD.findall(str(text or "").lower()):
        if chunk.isascii():
            out.add(chunk)
        else:
            out.update(chunk[index:index + 2] for index in range(max(1, len(chunk) - 1)))
    return out


def jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def mmr(items: list[dict], limit: int, *, lambda_: float = 0.7, text_of=None,
        score_of=None) -> list[dict]:
    """Greedy MMR. ``lambda_`` 1.0 is pure relevance, 0.0 pure novelty."""
    if limit <= 0 or not items:
        return []
    text_of = text_of or (lambda item: item.get("value"))
    score_of = score_of or (lambda item: float(item.get("score") or 0.0))
    if len(items) <= limit:
        return list(items)
    raw = [score_of(item) for item in items]
    low, high = min(raw), max(raw)
    span = (high - low) or 1.0
    relevance = [(score - low) / span for score in raw]
    bags = [tokens(text_of(item)) for item in items]
    chosen, remaining = [], list(range(len(items)))
    while remaining and len(chosen) < limit:
        best, best_value = None, None
        for index in remaining:
            redundancy = max((jaccard(bags[index], bags[other]) for other in chosen), default=0.0)
            value = lambda_ * relevance[index] - (1.0 - lambda_) * redundancy
            if best_value is None or value > best_value:
                best, best_value = index, value
        chosen.append(best)
        remaining.remove(best)
    return [items[index] for index in chosen]


__all__ = ["tokens", "jaccard", "mmr"]
