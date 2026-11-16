"""Keep producer claims from superseding reviewed state or conflicting peers."""
from collections import defaultdict

from .contracts import parse_instant


_OWNED = {'CURRENT_CONFIRMED', 'CONFLICT_UNRESOLVED'}


def _identity(item):
    entity, slot = item.get('entity'), item.get('slot')
    if isinstance(entity, str) and isinstance(slot, str):
        return entity.strip().casefold(), slot.strip().casefold()
    return None


def latest_user_observation(item, sources):
    times = []
    for citation in item.get('citations', ()):
        source = sources.get(citation['turn'])
        if citation['field'] == 'user' and source and citation['quote'] in source['user']:
            times.append(source['time'])
    return max(times, key=parse_instant, default=None)


def coherent_producer_items(reviewed, produced, *, observation_sources=None):
    owned = {_identity(item) for item in reviewed if item['kind'] in _OWNED} - {None}
    disputed = {_identity(item) for item in produced if item['kind'] == 'CONFLICT_UNRESOLVED'} - {None}
    currents = defaultdict(list)
    for item in produced:
        key = _identity(item)
        if key is not None and key not in owned and item['kind'] == 'CURRENT_CONFIRMED':
            currents[key].append(item)

    kept = []
    emitted = set()
    for item in produced:
        key = _identity(item)
        if item['kind'] in _OWNED and key in owned:
            continue
        if item['kind'] != 'CURRENT_CONFIRMED' or key is None:
            kept.append(item)
            continue
        if key in disputed:
            continue
        if key in emitted:
            continue
        emitted.add(key)
        group = currents[key]
        values = list(dict.fromkeys(row['value'] for row in group))
        if len(values) == 1:
            winner = item
            if len(group) > 1 and observation_sources is not None:
                observed = [(time, row) for row in group
                            if (time := latest_user_observation(row, observation_sources)) is not None]
                if observed:
                    winner = max(observed, key=lambda candidate: parse_instant(candidate[0]))[1]
            kept.append(winner)
            continue
        refs = tuple(sorted({ref for row in group for ref in row['source_turns']}))
        cites = [cite for row in group for cite in row.get('citations', ())]
        text = (f'[CONFLICT_UNRESOLVED] {item["entity"]} / {item["slot"]} = '
                + ' | '.join(values) + f'；来源轮次 {",".join(map(str, refs))}')
        kept.append({**item, 'kind': 'CONFLICT_UNRESOLVED', 'value': values, 'text': text,
                     'source_turns': refs, 'citations': cites})
    return kept
