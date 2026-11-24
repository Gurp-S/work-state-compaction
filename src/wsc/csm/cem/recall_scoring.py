"""Deterministic positive overlap weights across Python hash seeds."""
import math


def overlap_weight(shared, frequency, total):
    return math.fsum(math.log1p(total / (1 + frequency[term])) for term in sorted(shared))
