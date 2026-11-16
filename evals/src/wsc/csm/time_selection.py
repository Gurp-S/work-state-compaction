"""Revision selection compares instants and respects explicit validity anchors."""
from .contracts import parse_instant


def as_of(records, instant: str) -> dict | None:
    target = parse_instant(instant)
    chosen, chosen_key = None, None
    for record in records:
        start = record.get("valid_from") or record.get("effective_at")
        if not start:
            continue
        when = parse_instant(start)
        key = (when, int(record.get("revision") or 0))
        if when <= target and (chosen_key is None or key > chosen_key):
            chosen, chosen_key = record, key
    return chosen
