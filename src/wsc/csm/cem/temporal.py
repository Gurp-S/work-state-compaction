"""Interval algebra for time-scoped memories: arithmetic only, never interpretation.

A revision's validity is an interval, not a point, so "before / after / during / overlapping"
questions are answered by comparing intervals. The caller's model decides which interval a
question means; this module only refuses to guess when an endpoint is unknown.
"""
from __future__ import annotations

from datetime import datetime, timezone

_MAX = datetime.max.replace(tzinfo=timezone.utc)


def moment(value):
    """Parse one ISO-8601 instant; a naive value is read as UTC. None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def window(start=None, end=None) -> tuple:
    """Normalize a caller window; an inverted window is an error, not a silent swap."""
    low, high = moment(start), moment(end)
    if low is not None and high is not None and low > high:
        from ..contracts import require

        require(False, "temporal_window_inverted")
    return (low, high)


def span(record: dict) -> tuple:
    """The interval a revision claims: valid_from (else effective_at) through valid_to."""
    start = moment(record.get("valid_from")) or moment(record.get("effective_at"))
    return (start, moment(record.get("valid_to")))


def _ordered(value: tuple) -> tuple:
    start, end = value
    return (start, end if end is not None else _MAX)


def intersects(left: tuple, right: tuple):
    """True/False when both starts are known; None means undecidable, not empty."""
    low, high = _ordered(left), _ordered(right)
    if low[0] is None or high[0] is None:
        return None
    return low[0] <= high[1] and high[0] <= low[1]


def relation(left: tuple, right: tuple) -> str:
    """equals / contains / contained / overlaps / meets / before / after / unknown."""
    if intersects(left, right) is None:
        return "unknown"
    low, high = _ordered(left), _ordered(right)
    if low == high:
        return "equals"
    if low[0] <= high[0] and low[1] >= high[1]:
        return "contains"
    if high[0] <= low[0] and high[1] >= low[1]:
        return "contained"
    if low[1] < high[0]:
        return "before"
    if high[1] < low[0]:
        return "after"
    if low[1] == high[0] or high[1] == low[0]:
        return "meets"
    return "overlaps"


def clip(value: tuple, bounds: tuple):
    """Narrow one interval to a window; None when the window excludes it entirely."""
    if intersects(value, bounds) is not True:
        return None
    low, high = _ordered(value), _ordered(bounds)
    start = low[0] if high[0] is None or low[0] >= high[0] else high[0]
    end = low[1] if high[1] is None or low[1] <= high[1] else high[1]
    return (start, None if end == _MAX else end)


def duration(value: tuple):
    """Seconds the interval covers; None when either endpoint is unknown."""
    start, end = _ordered(value)
    if start is None or end == _MAX:
        return None
    return (end - start).total_seconds()


def contains_instant(value: tuple, when):
    """True/False/None: whether one instant falls inside an interval."""
    at = moment(when) if isinstance(when, str) else when
    low = _ordered(value)
    if at is None or low[0] is None:
        return None
    return low[0] <= at <= low[1]


def between(records: list[dict], start=None, end=None) -> list[dict]:
    """Records whose validity intersects the window, ordered by start then identity."""
    bounds = window(start, end)
    kept = [record for record in records if intersects(span(record), bounds) is not False]
    return sorted(kept, key=lambda record: (_ordered(span(record))[0] or _MAX,
                                            str(record.get("memory_id"))))


__all__ = ["moment", "window", "span", "intersects", "relation", "clip", "duration",
           "contains_instant", "between"]
