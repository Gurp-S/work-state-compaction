"""Keep temporal applicability separate from question applicability."""


def candidate_temporal_items(items):
    """A model date projection establishes a date candidate, not request binding."""
    projected = []
    for item in items:
        kind = item['kind']
        if kind not in ('DUE', 'DEADLINE_DATE') or item.get('status') != 'source_projection':
            projected.append(item)
            continue
        quotes = list(dict.fromkeys(cite['quote'] for cite in item.get('citations', ())
                                    if cite['field'] == 'user' and len(cite['quote']) <= 160))
        source_turns = ','.join(map(str, item['source_turns']))
        date = (item.get('due_start') or '')[:10]
        date_label = '原文截止日期' if kind == 'DEADLINE_DATE' else '原文日期'
        temporal = f'{date_label} {date}；' if date else ''
        text = f'[PENDING_BINDING] {temporal}事项对本轮的适用性未确认；来源轮次 {source_turns}'
        if quotes:
            text += '；用户原话：' + ' / '.join(quotes[:2])
        projected.append({**item, 'kind': 'PENDING_BINDING', 'text': text,
                          'reason': 'request_binding_required', 'projected_kind': kind})
    return projected


def scope_temporal_items(items, calendar_only):
    """Retain date-only discoveries as pending until the request binds them."""
    scoped = []
    for item in items:
        if (item['kind'] in ('DUE', 'DEADLINE_DATE')
                and set(item['source_turns']) <= calendar_only):
            kind = item['kind']
            scoped.append({**item, 'kind': 'PENDING_BINDING',
                           'reason': 'calendar_only_source',
                           'text': item['text'].replace(f'[{kind}]', '[PENDING_BINDING]', 1)
                           + '；时间锚点已核对，当前问题指向未确认'})
        else:
            scoped.append(item)
    return scoped
