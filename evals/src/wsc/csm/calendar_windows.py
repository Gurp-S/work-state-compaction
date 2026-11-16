"""Resolve literal, inclusive-start spans expressed in local calendar days."""
from datetime import datetime, timedelta
import re

from .calendar_anchors import _isolated_expression, _number, resolve_calendar_day


_WINDOW = re.compile(r'从(今天|明天|后天)起(?:吃|服用|持续|连续|共)?([0-9一二三四五六七八九十两]{1,3})天')


def resolve_source_calendar_window(expression, field, observed_at):
    match = _WINDOW.fullmatch(expression)
    if match is None or not _isolated_expression(expression, field):
        return None
    left, right = field.split(expression, 1)
    if (re.search(r'(?:没|没有|不是|不必|不用|如果|假如|大概|大约)\s*$', left)
            or re.match(r'\s*(?:半|多|起|以上|以下|或|到|至|[-—~～])', right)):
        return None
    day = resolve_calendar_day(match[1], observed_at)
    if day is None:
        return None
    try:
        days = _number(match[2])
        if days <= 0:
            return None
        end = datetime.fromisoformat(day[0]) + timedelta(days=days)
        return day[0], end.isoformat()
    except (OverflowError, ValueError):
        return None


def find_source_calendar_windows(field, observed_at):
    """Yield verbatim offsets and intervals recognized by the same resolver."""
    for match in _WINDOW.finditer(field):
        window = resolve_source_calendar_window(match[0], field, observed_at)
        if window is not None:
            yield match.start(), match.end(), match[0], window
