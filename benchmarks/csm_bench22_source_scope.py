"""Keep model-produced interpretations scoped to their source observations."""
from wsc.csm.cem.state_merge import latest_user_observation


def scope_source_accounts(items, sources):
    scoped = []
    for item in items:
        if item['kind'] != 'CURRENT_CONFIRMED' or item.get('status') != 'source_projection':
            scoped.append(item)
            continue
        through = latest_user_observation(item, sources)
        text = item['text'].replace('[CURRENT_CONFIRMED]', '[SOURCE_ACCOUNT]', 1)
        boundary = f'用户原话截至 {through}' if through is not None else '用户原话时间未核验'
        scoped.append({**item, 'kind': 'SOURCE_ACCOUNT', 'source_through': through,
                       'text': f'{text}；{boundary}；本轮适用性未确认'})
    return scoped
