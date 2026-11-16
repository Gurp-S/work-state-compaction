"""Find literal temporal and lifecycle spans for review without asserting state."""
from dataclasses import dataclass
import re

from .calendar_anchors import MONTH_END, resolve_source_calendar_day, resolve_source_deadline_date


_NUMBER = r'[0-9一二三四五六七八九十两]{1,3}'
_WEEKDAY = r'(?:周|星期)[一二三四五六日天]'
_EN_WEEKDAY = r'(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)'
_CALENDAR = re.compile(
    rf'(?<![0-9])[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}(?![0-9])'
    rf'|(?:(?:[0-9]{{4}}年)?{_NUMBER}月|这个月|本月|下个月|下月)?{_NUMBER}[日号](?!期|子|码)'
    rf'|(?:这|本|下|上|每|这个|下个|上个)?{_WEEKDAY}(?:\s*(?:到|至)\s*{_WEEKDAY})?'
    rf'|{MONTH_END}'
    rf'|大后天|今天|明天|后天|昨天|前天'
    rf'|\b(?:(?:this|next|last|every) )?{_EN_WEEKDAY}\b'
    rf'|\b(?:day after tomorrow|today|tomorrow|yesterday)\b',
    re.IGNORECASE,
)
_TRANSITION = re.compile(
    r'取消了?|作废|推迟|延期|改期|提前到|已经完成|已完成|'
    r'\b(?:cancell?ed|rescheduled|postponed|completed)\b', re.IGNORECASE,
)
_DEADLINE_PREFIX = re.compile(r'(?:(?:截至|不晚于)\s*|\b(?:no later than|before|by)\s+)$', re.I)
_DEADLINE_SUFFIX = re.compile(r'^\s*(?:之前|以前|前)(?!往|后)')


@dataclass(frozen=True)
class CommitmentCandidate:
    source_id: str
    field: str
    start: int
    end: int
    text: str
    kind: str
    day: tuple[str, str] | None


def discover_commitment_candidates(source_id: str, field: str, text: str,
                                   observed_at: str) -> tuple[CommitmentCandidate, ...]:
    """Return verbatim offsets. A parsed day dates the expression only."""
    candidates = []
    for kind, pattern in (('calendar', _CALENDAR), ('lifecycle_cue', _TRANSITION)):
        for match in pattern.finditer(text):
            start, end = match.span()
            if kind == 'calendar':
                prefix = _DEADLINE_PREFIX.search(text[:start])
                suffix = _DEADLINE_SUFFIX.match(text[end:])
                if (prefix is None) != (suffix is None):
                    lower = prefix.start() if prefix else start
                    upper = end + suffix.end() if suffix else end
                    expression = text[lower:upper]
                    deadline = resolve_source_deadline_date(expression, text, observed_at)
                    if deadline:
                        candidates.append(CommitmentCandidate(
                            source_id, field, lower, upper, expression, 'deadline_date', deadline))
                        continue
            expression = text[start:end]
            day = resolve_source_calendar_day(expression, text, observed_at) if kind == 'calendar' else None
            candidates.append(CommitmentCandidate(source_id, field, start, end, expression, kind, day))
    return tuple(sorted(candidates, key=lambda candidate: candidate.start))
