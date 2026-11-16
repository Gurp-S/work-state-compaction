"""Publish source-backed state together with the exact supporting spans."""
from collections import defaultdict

from wsc.csm.commitment_candidate_state import with_candidates
from wsc.csm.state_extraction import render_items


def _item_spans(item):
    if 'source_spans' in item:
        return item['source_spans']
    return [{'event_id': f"chat/{cite['turn']}", 'path': [cite['field']], 'quote': cite['quote']}
            for cite in item.get('citations', ())]


def fit_state_evidence(items, selected, *, read_original, source_block, visible, budget, heading,
                       retain_cited_exchange=False, overflow=None):
    without_spans = [item for item in items if not _item_spans(item)]
    kept = []
    replacements = {}
    rejected_turns = set()
    rejected_reason = 'state_evidence_budget'
    spans = []
    originals = {}
    required = {}

    def blocks_for(citations):
        fields = defaultdict(lambda: {'user': [], 'assistant': []})
        for span in citations:
            prefix, _, seq = span['event_id'].partition('/')
            path = span['path']
            if prefix != 'chat' or not seq.isdecimal() or path not in (['user'], ['assistant']):
                return None
            position = int(seq) - 1
            if position not in visible:
                return None
            if position not in originals:
                originals[position] = read_original(position)
            field, quote = path[0], span['quote']
            if quote not in originals[position][field]:
                raise ValueError('reviewed_source_quote_mismatch')
            if quote not in fields[position][field]:
                fields[position][field].append(quote)
        return {position: source_block({**originals[position], '_full': originals[position],
                                       **{field: '\n[…]\n'.join(quotes) for field, quotes in roles.items()}})
                for position, roles in fields.items()}

    def fit_item(item):
        proposed = spans + _item_spans(item)
        blocks = blocks_for(proposed)
        if blocks is None:
            return None, 'state_evidence_not_renderable'
        state_text = render_items(without_spans + kept + [item])
        cost = len(state_text) + len(heading) + 2 + sum(len(block) + 2 for block in blocks.values())
        if cost > budget:
            return None, 'state_evidence_budget'
        return (proposed, blocks), None

    for index, item in enumerate(items):
        item_spans = _item_spans(item)
        if not item_spans:
            continue
        published = item
        fitted, reason = fit_item(item)
        if fitted is None and 'candidate_count' in item:
            retained = []
            for candidate in item['candidates']:
                partial = with_candidates(item, [*retained, candidate])
                attempt, _ = fit_item(partial)
                if attempt is not None:
                    retained.append(candidate)
                    published, fitted = partial, attempt
        if fitted is None:
            rejected_turns.update(item['source_turns'])
            rejected_reason = reason
            continue
        rejected_turns.update(set(item['source_turns']) - set(published['source_turns']))
        kept.append(published)
        replacements[index] = published
        spans, required = fitted

    remaining = [replacements.get(index, item) for index, item in enumerate(items)
                 if index in replacements or not _item_spans(item)]
    if len(remaining) == 1:
        detail = ('状态引文超出上下文预算。' if rejected_reason == 'state_evidence_budget'
                  else '状态来源无法作为对话引文呈现。')
        remaining.append({'kind': 'NO_CONFIRMED_STATE', 'source_turns': (), 'reason': rejected_reason,
                          'text': f'[NO_CONFIRMED_STATE] {detail}'})
    state_text = render_items(remaining)
    allowance = budget - len(state_text) - len(heading) - 2 - sum(len(block) + 2 for block in required.values())
    # The first pass prices whole exchanges. A verified excerpt can free space
    # for an already ranked exchange that did not fit at that point.
    ranked_blocks = selected.items() if not overflow else (*selected.items(), *overflow.items())
    for position, block in ranked_blocks:
        if position not in required and len(block) + 2 <= allowance:
            required[position] = block
            allowance -= len(block) + 2
    if retain_cited_exchange:
        # Spend remaining budget on context after allocating independent evidence.
        for position, original in originals.items():
            if position not in required:
                continue
            full = source_block(original)
            extra = len(full) - len(required[position])
            if extra <= allowance:
                required[position] = full
                allowance -= extra
    retained_turns = {turn for item in remaining for turn in item.get('source_turns', ())}
    return remaining, state_text, required, rejected_turns - retained_turns, spans
