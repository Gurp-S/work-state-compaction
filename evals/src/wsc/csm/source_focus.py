"""Resolve equal window scores using evidence in the anchor turn itself."""
import json

from .recall_scoring import overlap_weight
from .recall_terms import terms


def rank_tied_windows(indices, candidates, centers, wanted, frequency, population):
    def order(index):
        turn = centers[index]
        if turn is None:
            central_score = 0
        else:
            content = ' '.join(str(turn.get(key) or '') for key in ('text', 'blip_caption'))
            central_score = overlap_weight(wanted & terms(content), frequency, population)
        candidate = candidates[index]
        size = len(json.dumps(candidate['value'], ensure_ascii=False, separators=(',', ':')))
        return -central_score, size, candidate['memory_id']

    return sorted(indices, key=order)
