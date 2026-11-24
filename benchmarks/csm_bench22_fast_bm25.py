"""Offline candidate for exact top-k with precomputed document length factors."""
from collections import defaultdict
from heapq import nsmallest
from math import log

from bench22.systems import tokens


def fast_top(index, query, k):
    if k <= 0 or not index.dl or not index.total:
        return []
    size = len(index.dl)
    avg = index.total / size
    norm = [index.k1 * (1 - index.b + index.b * length / avg) for length in index.dl]
    scores = defaultdict(float)
    for term in dict.fromkeys(tokens(query)):
        posting = index.post.get(term)
        if not posting:
            continue
        df = len(posting)
        idf = log(1 + (size - df + 0.5) / (df + 0.5))
        for position, frequency in posting:
            scores[position] += idf * frequency * (index.k1 + 1) / (frequency + norm[position])
    return nsmallest(k, scores, key=lambda position: (-scores[position], position))
