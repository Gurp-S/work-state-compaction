"""Project source-backed recurring contact constraints against a requested time."""
from datetime import datetime, time, timedelta
import re

from wsc.csm.calendar_anchors import _number


_DIGITS = r'0-9一二三四五六七八九十两'
_HOUR = rf'([{_DIGITS}]{{1,3}})(?:点|时)(?!\s*[半钟{_DIGITS}])'
_PERIOD = r'(凌晨|早上|上午|中午|下午|傍晚|晚上)'
_RULE = re.compile(r'(?:每个?)(?:周|星期)([一二三四五六日天])' + _PERIOD + _HOUR + r'(?:到|至)' + _HOUR
                   + r'[^。！？；\n]{0,42}?你(?:也)?(?:别|不要|不用)主动(?:联系我|找我|给我发消息|打扰我|叫我|喊我)')
_REQUEST = re.compile(r'(今天|明天|后天|今晚|明晚|后晚)?' + _PERIOD + '?' + _HOUR
                      + r'[^。！？；\n]{0,15}?(?:提醒我|叫我|喊我|联系我|给我发消息)')
_REPORTED = re.compile(r'(?:如果|假如|假设|也许|可能|以前|之前|不是|曾经|有时|她说|他说|提议|转述|取消|不用再|不再)')


def _hour(number, period):
    value = _number(number)
    if period in ('下午', '傍晚', '晚上') and 1 <= value <= 11:
        value += 12
    if value >= 24 or value < 0 or (period is None and value < 13):
        raise ValueError('ambiguous_contact_hour')
    return value


def _requested_time(question, now):
    if _REPORTED.search(question) or re.search(r'(?:不用|不要|别)\s*(?:提醒|喊|叫|联系|给我发)', question):
        return None
    requests = list(_REQUEST.finditer(question))
    if len(requests) != 1:
        return None
    day, period, raw_hour = requests[0].groups()
    if not day or re.search(r'周[一二三四五六日天]|星期[一二三四五六日天]', question):
        return None
    clock = datetime.fromisoformat(now)
    try:
        hour = _hour(raw_hour, period or ('晚上' if day.endswith('晚') else None))
        offset = {'今': 0, '明': 1, '后': 2}[day[0]]
        target = datetime.combine(clock.date() + timedelta(days=offset), time(hour), clock.tzinfo)
    except (ValueError, OverflowError):
        return None
    return target if clock.tzinfo is not None and target >= clock else None


def contact_window_state(question, now, sources):
    """Return an overlap with a recorded restriction, leaving overrides undecided."""
    requested = _requested_time(question, now)
    if requested is None:
        return None
    candidates = []
    for source in sources:
        observed = datetime.fromisoformat(source['time'])
        if observed.tzinfo is None or observed > datetime.fromisoformat(now):
            continue
        local = requested.astimezone(observed.tzinfo)
        for line in source['user'].splitlines():
            if _REPORTED.search(line) or '？' in line or '?' in line:
                continue
            for match in _RULE.finditer(line):
                weekday, period, raw_start, raw_end = match.groups()
                try:
                    start, end = _hour(raw_start, period), _hour(raw_end, period)
                except ValueError:
                    continue
                if '一二三四五六日'.index(weekday.replace('天', '日')) == local.weekday() and start <= local.hour < end:
                    candidates.append((observed, source['turn'], match.group(), start, end, local))
    if not candidates:
        return None
    _, turn, quote, start, end, local = max(candidates, key=lambda row: (row[0], row[1]))
    return {'kind': 'PENDING_BINDING', 'reason': 'recorded_contact_window_exception_unresolved',
            'source_turns': [turn], 'citations': [{'turn': turn, 'field': 'user', 'quote': quote}],
            'requested_at': local.isoformat(), 'local_window_hours': [start, end],
            'text': f'[PENDING_BINDING] 本次主动联系请求 {local.isoformat()} 落在曾记录的限制时段 '
                    f'{start:02}:00–{end:02}:00；本次是否例外未确认；来源轮次 {turn}'}
