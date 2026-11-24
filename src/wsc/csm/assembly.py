"""Context assembly: utility-ordered blocks under a character budget.

The budget is spent by usefulness, not by row order. Current confirmed memories come first;
historical and unknown rows are kept only when budget remains. Evidence is attached in the
same block, and when an item does not fit, its evidence is excerpted rather than the item
being dropped whole, so a fact never arrives without the source it rests on.
"""
from __future__ import annotations

import json

from .contracts import CURRENT_CONFIRMED, HISTORICAL, UNKNOWN, require

_CLASS_ORDER = {CURRENT_CONFIRMED: 0, HISTORICAL: 1, UNKNOWN: 2}


def _core(item: dict) -> dict:
    row = {"memory_id": item.get("memory_id"), "entity": item.get("entity"),
           "slot": item.get("slot"), "value": item.get("value"),
           "classification": item.get("classification")}
    for key in ("status", "property_kind", "scope", "revision", "valid_from", "effective_at"):
        if item.get(key) is not None:
            row[key] = item[key]
    return row


def _size(item: dict) -> int:
    return len(json.dumps(item, ensure_ascii=False, sort_keys=True))


def _evidence_block(item: dict, budget: int) -> list[dict]:
    """Keep as much source text as fits; a truncated excerpt still names its event."""
    if budget <= 0:
        return []
    out = []
    for entry in item.get("evidence") or []:
        room = budget - _size({"evidence": out})
        if room <= 2:
            break
        text = str(entry.get("text") or "")
        take = text[:max(0, room - 80)]
        if not take:
            break
        out.append({"source_id": entry.get("source_id"),
                    "observed_at": entry.get("observed_at"), "text": take})
    return out


def assemble(result: dict, *, max_chars: int = 4000, max_items: int = 20) -> dict:
    """Build one bounded context block; omitted items are counted, never silently reshaped."""
    require(isinstance(max_chars, int) and max_chars > 0, "assembly_budget_invalid")
    require(isinstance(max_items, int) and max_items > 0, "assembly_budget_invalid")
    candidates = sorted(result.get("results", []), key=lambda item: (
        _CLASS_ORDER.get(item.get("classification"), 3), -(item.get("score") or 0.0)))
    items, used, omitted = [], 0, 0
    for candidate in candidates:
        if len(items) >= max_items:
            omitted += 1
            continue
        core = _core(candidate)
        cost = _size(core)
        if used + cost > max_chars:
            omitted += 1
            continue
        used += cost
        block = dict(core)
        source = _evidence_block(candidate, max_chars - used)
        if source:
            block["evidence"] = source
            used += _size({"evidence": source})
        items.append(block)
    return {"items": items, "used_chars": used, "max_chars": max_chars, "max_items": max_items,
            "omitted": omitted, "counts": result.get("counts", {})}


__all__ = ["assemble"]
