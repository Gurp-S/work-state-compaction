"""Rank complete original sentence windows within a selected source."""
from csm_bench22_candidate_delivery import append_source_candidate
from csm_bench22_semantic_delivery import _sentence_spans
from csm_bench22_recall_lanes import _segments


def rerank_source_passages(system, result, source_turn, question, embedder, *, now, cutoff_turn):
    """Rerank within one source, with unchanged visibility and publication limits."""
    if system.tail_start is not None or 'evidence_spans' in result.meta or source_turn in result.used_turns:
        return result
    source = system.read_original(source_turn, now=now, cutoff_turn=cutoff_turn)
    windows = list(dict.fromkeys([
        *_sentence_spans(source['user'], set(), include_semantic=True),
        *((start, text) for start, text in _segments(source['user'], True) if text.strip() and len(text) <= 320),
    ]))
    if not windows:
        return result
    query = embedder.query(question)[0]
    scores = embedder.embed([quote for _, quote in windows]) @ query
    for index in sorted(range(len(windows)), key=lambda i: (-float(scores[i]), windows[i][0])):
        start, quote = windows[index]
        candidate = {'turn': source_turn, 'field': 'user', 'start': start, 'end': start + len(quote), 'quote': quote}
        added = append_source_candidate(system, result, candidate, result.state_items, now=now, cutoff_turn=cutoff_turn,
                                        label='语义召回候选', reason='semantic_request_binding_unverified')
        if added is not result:
            return added
    return result
