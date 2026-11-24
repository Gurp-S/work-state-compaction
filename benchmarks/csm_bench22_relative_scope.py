"""Scope relative-day producer claims to the observations that support them."""
import re

from wsc.csm.cem.calendar_anchors import resolve_source_calendar_day
from wsc.csm.contracts import parse_instant


_LEADING_DAY = re.compile(r'^(今天|明天|后天|昨天|前天|大后天)(?:[（(](\d{4}-\d{2}-\d{2})[）)])?')


def scope_relative_current(items, sources, now):
    clock = parse_instant(now)
    scoped = []
    for item in items:
        match = _LEADING_DAY.match(item['value']) if item['kind'] == 'CURRENT_CONFIRMED' else None
        if match is None:
            scoped.append(item)
            continue
        days = {}
        for cite in item.get('citations', ()):
            if cite['field'] != 'user' or match[1] not in cite['quote']:
                continue
            source = sources.get(cite['turn'])
            if source is None or cite['quote'] not in source['user']:
                continue
            original = source.get('_full', source)
            day = resolve_source_calendar_day(match[1], original['user'], source['time'])
            if day is not None:
                days.setdefault(day, cite)
        if len(days) != 1:
            scoped.append(item)
            continue
        (start, end), cite = next(iter(days.items()))
        source_date = start[:10]
        if match[2] is not None and match[2] != source_date:
            reason = 'relative_date_conflict'
            detail = '模型日期与原文相对日期不一致'
        elif not parse_instant(start) <= clock < parse_instant(end):
            reason = 'relative_date_off_day'
            detail = '原话所指日期与查询日期不同'
        else:
            scoped.append(item)
            continue
        refs = ','.join(map(str, item['source_turns']))
        text = f'[PENDING_BINDING] {item["entity"]} / {item["slot"]}；原文所指日期 {source_date}；{detail}；来源轮次 {refs}'
        if len(cite['quote']) <= 160:
            text += f'；用户原话：{cite["quote"]}'
        scoped.append({**item, 'kind': 'PENDING_BINDING', 'text': text, 'reason': reason, 'source_date': source_date})
    return scoped
