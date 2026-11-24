"""Publish exact user excerpts within unused final prompt capacity."""
from csm_bench22 import StateRetrieval
from csm_bench22_passage_binding import verify_passage
from wsc.csm.cem.state_extraction import render_items


def append_source_candidate(system, result, candidate, items, *, now, cutoff_turn, label, reason):
    return append_source_candidates(system, result, [candidate], items, now=now, cutoff_turn=cutoff_turn,
                                    label=label, reason=reason)


def append_source_candidates(system, result, candidates, items, *, now, cutoff_turn, label, reason):
    candidates = tuple(candidates)
    if any(candidate['field'] != 'user' for candidate in candidates):
        raise ValueError('candidate_user_source_required')
    if system.tail_start is not None or 'evidence_spans' in result.meta:
        return result
    candidates = [candidate for candidate in candidates if candidate['turn'] not in result.used_turns]
    if not candidates:
        return result
    sources = [(candidate, system.read_original(candidate['turn'], now=now, cutoff_turn=cutoff_turn))
               for candidate in candidates]
    for candidate, source in sources:
        verify_passage(candidate, source)
    originals = result.meta.get('evidence_turns', result.used_turns)
    blocks = {seq: system._source_block(system.read_original(seq, now=now, cutoff_turn=cutoff_turn))
              for seq in originals}
    heading = '【证据｜仅支撑】\n【聊天记录】'
    previous = '\n\n'.join([heading, *blocks.values()]) if blocks else ''
    if result.evidence != previous:
        return result
    kept = [item for item in items if item['kind'] != 'NO_CONFIRMED_STATE']
    spans = []
    for candidate, source in sources:
        turn, quote = candidate['turn'], candidate['quote']
        if turn in blocks:
            continue
        block = system._source_block({**source, '_full': source, 'user': quote, 'assistant': ''})
        span = {'event_id': f'chat/{turn}', 'path': ['user'], 'quote': quote}
        item = {'kind': 'PENDING_BINDING', 'reason': reason, 'text': f'[PENDING_BINDING] {label}；来源轮次 {turn}',
                'source_turns': [turn], 'source_spans': [span]}
        trial_state = render_items([*kept, item])
        trial_evidence = '\n\n'.join([heading, *blocks.values(), block])
        if len(trial_state) + 2 + len(trial_evidence) <= 6400:
            blocks[turn] = block
            kept.append(item)
            spans.append(span)
    if not spans:
        return result
    turns = sorted(blocks)
    state = render_items(kept)
    evidence = '\n\n'.join([heading, *(blocks[seq] for seq in turns)])
    added = StateRetrieval(kept, state, evidence, sorted(set(result.used_turns) | blocks.keys()))
    added.meta.update({**result.meta, 'state_items': kept, 'evidence_turns': turns, 'evidence_spans': spans})
    return added
