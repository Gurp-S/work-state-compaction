"""Mechanical restatements may save revisions; semantic similarity cannot erase updates."""
from ..contracts import encode


def restates(previous: dict, candidate: dict) -> bool:
    for field in ("semantic_type", "status", "lifecycle"):
        if previous[field] != candidate[field]:
            return False
    for field in ("valid_from", "event_group"):
        if candidate.get(field) is not None and candidate[field] != previous.get(field):
            return False
    left, right = previous["value"], candidate["value"]
    if isinstance(left, str) and isinstance(right, str):
        # Only a terminal full stop is formatting here. Internal punctuation, digits,
        # negation and token overlap carry information and are left intact.
        return left.strip().rstrip("。").strip() == right.strip().rstrip("。").strip()
    return encode(left) == encode(right)
