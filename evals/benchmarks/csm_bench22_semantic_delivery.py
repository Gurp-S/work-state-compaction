"""Select a budget-fitting original from a bounded semantic candidate list."""
from bench22.systems import tokens
from csm_bench22_candidate_delivery import append_source_candidate
from csm_bench22_recall_lanes import _segments


def _sentence_spans(text, phrases, *, include_semantic=False):
    # Prefer contiguous original sentences and keep any adjacent qualifier
    # with the anchor when possible. Never trim inside an oversized sentence.
    sentences = [(start, sentence) for start, sentence in _segments(text, True) if sentence.strip()]
    ranked = []
    for i, (start, sentence) in enumerate(sentences):
        overlap = phrases.intersection(tokens(sentence))
        if (not overlap and not include_semantic) or len(sentence) > 320:
            continue
        left = sentences[i - 1][0] if i > 0 else start
        next_start, next_sentence = sentences[min(i + 1, len(sentences) - 1)]
        right = next_start + len(next_sentence)
        passage = text[left:right]
        if len(passage) > 320:
            passage = text[start:right]
            left = start
        if len(passage) <= 320 and passage != text:
            ranked.append((-len(overlap), left, passage))
    ordered = sorted(set(ranked))
    for _, start, passage in (ordered if include_semantic else ordered[:2]):
        yield start, passage


def supplement_semantic_sources(system, result, ranked_turns, *, now, cutoff_turn, question=None,
                                allow_passages=False):
    """Try unused candidates in rank order with optional phrase corroboration."""
    if system.tail_start is not None or 'evidence_spans' in result.meta:
        return result
    phrases = {term for term in tokens(question) if len(term) > 1} if question is not None else None
    passages = []
    for turn in ranked_turns[:5]:
        if turn in result.used_turns:
            continue
        source = system.read_original(turn, now=now, cutoff_turn=cutoff_turn)
        text = source['user']
        if not text.strip() or (phrases is not None and not phrases.intersection(tokens(text))):
            continue
        if len(text) <= 320:
            added = _append(system, result, turn, 0, text, now, cutoff_turn)
            if added is not result:
                return added
        if allow_passages and phrases:
            passages.append((turn, text))
    for turn, text in passages:
        for start, quote in _sentence_spans(text, phrases):
            added = _append(system, result, turn, start, quote, now, cutoff_turn)
            if added is not result:
                return added
    return result


def _append(system, result, turn, start, quote, now, cutoff_turn):
    candidate = {'turn': turn, 'field': 'user', 'start': start, 'end': start + len(quote), 'quote': quote}
    return append_source_candidate(
        system, result, candidate, result.state_items, now=now, cutoff_turn=cutoff_turn,
        label='语义召回候选', reason='semantic_request_binding_unverified',
    )
