"""Admit a produced conflict only with two distinct user assertions."""
from itertools import combinations


def _has_independent_user_citations(citations):
    witnesses = {(cite['turn'], cite['quote'].strip()) for cite in citations if cite['field'] == 'user'}
    # Nested excerpts from one turn can describe the same utterance twice.
    return any(left != right and (left_turn != right_turn or (left not in right and right not in left))
               for (left_turn, left), (right_turn, right) in combinations(witnesses, 2))


def scope_producer_conflicts(items):
    scoped = []
    for item in items:
        if item['kind'] != 'CONFLICT_UNRESOLVED' or item.get('status') != 'source_projection':
            scoped.append(item)
            continue
        if _has_independent_user_citations(item.get('citations', ())):
            scoped.append(item)
            continue
        refs = ','.join(map(str, item['source_turns']))
        pending = {key: value for key, value in item.items() if key != 'value'}
        scoped.append({**pending, 'kind': 'PENDING_BINDING', 'reason': 'conflict_source_required',
                       'text': f"[PENDING_BINDING] {item['entity']} / {item['slot']}；"
                               f'冲突的第二个用户来源未建立；来源轮次 {refs}'})
    return scoped


def suppress_unresolved_current(items):
    pending = {}
    for item in items:
        if item.get('reason') == 'conflict_source_required':
            key = item['entity'].strip().casefold(), item['slot'].strip().casefold()
            pending.setdefault(key, []).extend(cite for cite in item.get('citations', ()) if cite['field'] == 'user')

    retained = []
    for item in items:
        if item['kind'] == 'CURRENT_CONFIRMED' and item.get('status') == 'source_projection':
            key = item['entity'].strip().casefold(), item['slot'].strip().casefold()
            witnesses = [cite for cite in item.get('citations', ()) if cite['field'] == 'user']
            if key in pending and all(any(
                cite['turn'] == prior['turn'] and (cite['quote'] in prior['quote'] or prior['quote'] in cite['quote'])
                for prior in pending[key]
            ) for cite in witnesses):
                continue
        retained.append(item)
    return retained
