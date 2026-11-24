"""Resolve explicit single-day expressions relative to an observed local date."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta
import re


_ZH_WEEKDAYS = '一二三四五六日'
_EN_WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
_DAY_OFFSETS = {'今天': 0, '明天': 1, '后天': 2, '大后天': 3, '昨天': -1, '前天': -2,
                'today': 0, 'tomorrow': 1, 'day after tomorrow': 2, 'yesterday': -1}
MONTH_END = r'(?:(?:这个月|本月|下个月|下月|上个月|上月)(?:月底|月末|底|末)|月底|月末)'


def _number(text):
    if text.isascii() and text.isdigit():
        return int(text)
    digits = '零一二三四五六七八九'
    if text == '两':
        return 2
    if len(text) == 1 and text in digits:
        return digits.index(text)
    if '十' in text:
        tens, units = text.split('十', 1)
        if len(tens) <= 1 and len(units) <= 1 and (not tens or tens in digits) and (not units or units in digits):
            return (digits.index(tens) if tens else 1) * 10 + (digits.index(units) if units else 0)
    raise ValueError('invalid_calendar_number')


def _day(expression, observed):
    expression = expression.strip().lower()
    if expression in _DAY_OFFSETS:
        return observed + timedelta(days=_DAY_OFFSETS[expression])
    match = re.fullmatch(r'(这|本|下)(?:周|星期)([一二三四五六日天])', expression)
    if match:
        weekday = _ZH_WEEKDAYS.index(match[2].replace('天', '日'))
        return observed + timedelta(days=weekday - observed.weekday() + (7 if match[1] == '下' else 0))
    match = re.fullmatch(r'(this|next) (' + '|'.join(_EN_WEEKDAYS) + ')', expression)
    if match:
        return observed + timedelta(days=_EN_WEEKDAYS.index(match[2]) - observed.weekday()
                                    + (7 if match[1] == 'next' else 0))
    match = re.fullmatch(r'(这个月|本月|下个月|下月)([0-9一二三四五六七八九十两]{1,3})[日号]', expression)
    if match:
        month_index = observed.year * 12 + observed.month - 1 + int(match[1].startswith('下'))
        year, month = divmod(month_index, 12)
        return date(year, month + 1, _number(match[2]))
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', expression):
        return date.fromisoformat(expression)
    match = re.fullmatch(r'([0-9]{4})年([0-9一二三四五六七八九十两]{1,3})月([0-9一二三四五六七八九十两]{1,3})[日号]', expression)
    if match:
        return date(int(match[1]), _number(match[2]), _number(match[3]))
    return None


def _resolve_day(expression: str, observed_at: str, *, deadline=False) -> tuple[str, str] | None:
    """Return a half-open local-day interval in the explicitly observed offset."""
    try:
        observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
        if observed.tzinfo is None:
            return None
        if deadline and re.fullmatch(MONTH_END, expression):
            offset = int(expression.startswith('下')) - int(expression.startswith('上'))
            year, month_index = divmod(observed.year * 12 + observed.month - 1 + offset, 12)
            month = month_index + 1
            day = date(year, month, monthrange(year, month)[1])
        else:
            day = _day(expression, observed.date())
        if day is None:
            return None
        start = datetime.combine(day, time.min, observed.tzinfo)
        return start.isoformat(), (start + timedelta(days=1)).isoformat()
    except (ValueError, OverflowError):
        return None


def resolve_calendar_day(expression: str, observed_at: str) -> tuple[str, str] | None:
    """Return a half-open local-day interval in the explicitly observed offset."""
    return _resolve_day(expression, observed_at)


def _isolated_expression(expression, field):
    if not expression.strip() or field.count(expression) != 1:
        return False
    left, right = field.split(expression, 1)
    # A clipped span may omit an outer qualifier present in the source field.
    if re.search(r'(?:大|下|上|从|截至|不晚于|最晚|(?:\bby|\bbefore|\bafter|\bfrom)\s+)$', left, re.I):
        return False
    if re.match(r'\s*(?:之前|之后|以前|以后|前后|左右|前(?!往)|后(?!天)|至|到(?:大?后天|下周|周[一二三四五六日天])|'
                r'\b(?:or earlier|or later|through|until)\b)', right, re.I):
        return False
    if expression[0].isascii() and expression[0].isalnum() and re.search(r'[a-z0-9]$', left, re.I):
        return False
    if expression[-1].isascii() and expression[-1].isalnum() and re.match(r'[a-z0-9]', right, re.I):
        return False
    return True


def resolve_source_calendar_day(expression: str, field: str, observed_at: str) -> tuple[str, str] | None:
    """Resolve a named anchor only when it is an unambiguous day expression."""
    if _isolated_expression(expression, field):
        return resolve_calendar_day(expression, observed_at)
    return None


def resolve_source_deadline_date(expression: str, field: str, observed_at: str) -> tuple[str, str] | None:
    """Return the named date of a literal deadline without deciding inclusivity."""
    if not _isolated_expression(expression, field):
        return None
    suffix = re.fullmatch(r'(.+?)(?:之前|以前|前)', expression)
    prefix = re.fullmatch(r'(?:(?:截至|不晚于)\s*|(?:by|before|no later than)\s+)(.+)', expression, re.I)
    if prefix and re.search(r'\b(?:not|never)\s+$', field.split(expression, 1)[0], re.I):
        return None
    match = suffix or prefix
    return _resolve_day(match[1], observed_at, deadline=True) if match else None
