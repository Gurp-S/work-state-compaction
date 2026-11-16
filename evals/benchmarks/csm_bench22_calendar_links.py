"""Rank date-source candidates by shared user wording in retrieved originals."""
from math import log1p

from bench22.systems import tokens
from csm_bench22_recall_lanes import _segments
from wsc.csm.commitment_candidates import discover_commitment_candidates
from wsc.csm.contracts import parse_instant


def _score(index, candidate, anchor):
    shared = sorted(term for term in candidate & anchor if len(term) > 1)
    if len(shared) < 2:
        return None
    size = len(index.docs)
    weight = sum(log1p((size - len(index.post[term]) + 0.5) /
                       (len(index.post[term]) + 0.5)) ** 2 for term in shared)
    return weight / (len(candidate) * len(anchor)) ** 0.5, shared


def rank_calendar_links(user_index, anchors, date_candidates, *, limit=5):
    """The index and all positions refer to the same already-visible prefix."""
    scores = []
    for position in date_candidates:
        candidate = user_index.docs[position].keys()
        best = None
        for anchor in anchors:
            if anchor == position:
                continue
            match = _score(user_index, candidate, user_index.docs[anchor].keys())
            if match is None:
                continue
            score, shared = match
            if best is None or score > best[0]:
                best = (score, anchor, shared)
        if best is not None:
            scores.append((position, best))
    scores.sort(key=lambda entry: (-entry[1][0], -entry[0]))
    return [{'turn': position + 1, 'anchor_turn': anchor + 1, 'shared_terms': shared}
            for position, (_, anchor, shared) in scores[:limit]]


def rank_calendar_sentence_links(user_index, turns, anchors, date_candidates, *, clock, limit=5):
    """Match only sentences containing the matching date on the candidate side."""
    anchor_sentences = [(position, offset, text, set(tokens(text))) for position in anchors
                        for offset, text in _segments(turns[position]['user'], True) if text.strip()]
    best_by_turn = {}
    for position in date_candidates:
        turn = turns[position]
        user = turn['user']
        dates = discover_commitment_candidates(f'chat/{position + 1}', 'user', user, turn['time'])
        spans = [span for span in dates if span.day and parse_instant(span.day[0]) <= clock < parse_instant(span.day[1])]
        for offset, text in _segments(user, True):
            if not any(offset <= span.start and span.end <= offset + len(text) for span in spans):
                continue
            terms = set(tokens(text))
            for anchor, anchor_offset, anchor_text, anchor_terms in anchor_sentences:
                if position == anchor:
                    continue
                match = _score(user_index, terms, anchor_terms)
                if match is None:
                    continue
                score, shared = match
                if position not in best_by_turn or score > best_by_turn[position][0]:
                    best_by_turn[position] = (score, {'turn': position + 1, 'anchor_turn': anchor + 1,
                                                      'shared_terms': shared, 'start': offset, 'quote': text,
                                                      'anchor_start': anchor_offset, 'anchor_quote': anchor_text})
    order = sorted(best_by_turn, key=lambda position: (-best_by_turn[position][0], -position))
    return [best_by_turn[position][1] for position in order[:limit]]
