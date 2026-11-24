"""Offline lexical ranking with document term frequency capped at one."""
from collections import defaultdict
from heapq import nsmallest
from math import log

from bench22.systems import tokens
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_scope import rank_visible


def coverage_top(index, query, limit):
    if not index.total or limit <= 0:
        return []
    size = len(index.dl)
    avg = index.total / size
    scores = defaultdict(float)
    for term in dict.fromkeys(tokens(query)):
        posting = index.post.get(term)
        if not posting:
            continue
        df = len(posting)
        weight = log(1 + (size - df + 0.5) / (df + 0.5))
        for position, _ in posting:
            scores[position] += weight
    return nsmallest(limit, scores, key=lambda position: (
        -scores[position] * (index.k1 + 1) / (1 + index.k1 * (1 - index.b + index.b * index.dl[position] / avg)),
        position))


class TermCoverageBench22(RawMemoryBench22):
    def _rank_sources(self, question, visible):
        return rank_visible(question, self.turns, visible, self.user_index, self.full_index, top=coverage_top)
