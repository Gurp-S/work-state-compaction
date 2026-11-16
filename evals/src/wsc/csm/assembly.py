"""Context assembly (§13.6): ordered, budgeted, provenance-preserving.

CSM supplies evidence-backed memories; the caller decides the prose. Assembly therefore
trims, orders and reports what it omitted, but never rewrites a value, upgrades an
uncertainty and never drops the evidence that a claim rests on.
"""
from __future__ import annotations

import json

from .contracts import require
from .result_scope import loss_scope


def _item(result: dict) -> dict:
    """One assembly block: only fields a reader needs to judge the claim."""
    item = {"memory_id": result.get("memory_id"), "value": result.get("value"),
            "contexts": result.get("contexts", []),
            "evidence": result.get("source_refs", []),
            "classification": result.get("classification"),
            "reason": result.get("reason")}
    if result.get("status") is not None:
        item["status"] = result["status"]
    if result.get("dependencies"):
        item["dependencies"] = result["dependencies"]
    if result.get("uncertainty"):
        item["uncertainty"] = result["uncertainty"]
    if result.get("revision") is not None:
        item["revision"] = result["revision"]
    for key in ("entity", "slot", "record_type", "source_scope", "effective_at", "pending_id",
                "semantic_type", "lifecycle", "valid_from", "valid_to", "confirmed", "retrieval_via",
                "identity_classification"):
        if result.get(key) is not None:
            item[key] = result[key]
    return item


def assemble(result: dict, *, max_chars: int = 4000, max_items: int = 20) -> dict:
    """Build the bounded context block for one query result.

    ``max_chars`` is measured on the serialized block, so the budget holds whatever the
    value's own shape is. Items that do not fit are counted, not silently reshaped.
    """
    require(isinstance(max_chars, int) and max_chars > 0, "assembly_budget_invalid")
    require(isinstance(max_items, int) and max_items > 0, "assembly_budget_invalid")
    items, used, omitted = [], 0, 0
    for candidate in result.get("results", []):
        if len(items) >= max_items:
            omitted += 1
            continue
        item = _item(candidate)
        size = len(json.dumps(item, ensure_ascii=False, sort_keys=True))
        if used + size > max_chars:
            omitted += 1
            continue
        used += size
        items.append(item)
    return {"items": items, "used_chars": used, "max_chars": max_chars,
            "max_items": max_items, **loss_scope(result, omitted),
            "counts": result.get("counts", {})}


__all__ = ["assemble"]
