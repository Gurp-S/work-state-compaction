"""Offline comparison of corpus-specific term weights in lexical recall."""
from collections import defaultdict
from math import log1p

from bench22.systems import IncBM25, rrf, tokens
from csm_bench22_raw_memory import RawMemoryBench22


def specificity_top(index, terms, limit):
    size = len(index.dl)
    if not size or not index.total:
        return []
    average_length = index.total / size
    scores = defaultdict(float)
    for term in terms:
        posting = index.post.get(term)
        if not posting:
            continue
        idf = log1p((size - len(posting) + 0.5) / (len(posting) + 0.5))
        for position, frequency in posting:
            length_norm = 1 - index.b + index.b * index.dl[position] / average_length
            scores[position] += idf ** 2 * frequency * (index.k1 + 1) / (frequency + index.k1 * length_norm)
    return sorted(scores, key=lambda position: (-scores[position], position))[:limit]


class SpecificityRecallBench22(RawMemoryBench22):
    def _rank_sources(self, question, visible):
        if self.tail_start is not None:
            return super()._rank_sources(question, visible)
        terms = tuple(dict.fromkeys(tokens(question)))
        if len(visible) == len(self.turns):
            return rrf([specificity_top(index, terms, 32) for index in (self.user_index, self.full_index)])
        positions = list(visible)
        user, full = IncBM25(), IncBM25()
        for position in positions:
            turn = self.turns[position]
            user.add(turn['user'])
            full.add(turn['user'] + '\n' + turn['assistant'])
        return [positions[index] for index in rrf([specificity_top(user, terms, 32), specificity_top(full, terms, 32)])]
