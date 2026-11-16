"""Hard filters and state semantics applied *before* ranking, never after it.

Ranking over a superset and filtering the winners is how a stale or out-of-scope memory
reaches the caller: the top-k budget is spent on rows that then vanish. Every filter here
therefore runs on candidates, and every result carries the classification its own revision
earns — a superseded revision is HISTORICAL even when it scores highest.
"""
from __future__ import annotations

import os

from . import temporal

FLAGS = {"recall_term_cache": "WSC_CSM_RECALL_TERM_CACHE",
         "source_focus": "WSC_CSM_SOURCE_FOCUS",
         "recall_neighborhood": "WSC_CSM_RECALL_NEIGHBORHOOD",
         "filters": "WSC_CSM_FILTERS", "diversity": "WSC_CSM_DIVERSITY",
         "index": "WSC_CSM_INDEX", "multihop": "WSC_CSM_MULTIHOP",
         "alias": "WSC_CSM_ALIAS", "digest": "WSC_CSM_DIGEST", "tree": "WSC_CSM_TREE",
         "relconfirm": "WSC_CSM_REL_CONFIRM"}

_TRUTHY = {"1", "true", "yes", "on"}
_REJECTED = {"rejected", "retracted", "invalid", "refuted"}
_ENDED = {"closed", "ended", "expired", "archived"}
# 已定策略、默认生效的开关；其余旁路一律默认关，等 A/B 证明收益再并主线。
_ON_BY_DEFAULT = {"relconfirm"}


def enabled(name: str) -> bool:
    """Bypass switch: new behaviour is opt-in until A/B shows it pays for itself."""
    default = "1" if name in _ON_BY_DEFAULT else "0"
    return os.environ.get(FLAGS[name], default).strip().lower() in _TRUTHY


def classify(record: dict, head_revision: int | None, *, lifecycle: str | None = None) -> tuple:
    """(classification, reason) from the revision's own standing, not from its score."""
    if str(record.get("status") or "").lower() in _REJECTED:
        return "UNKNOWN", "record_rejected"
    if head_revision is not None and record.get("revision") != head_revision:
        return "HISTORICAL", "superseded_revision"
    if str(lifecycle or record.get("lifecycle") or "").lower() in _ENDED:
        return "HISTORICAL", "lifecycle_closed"
    if record.get("certainty") == "SPECULATIVE":
        return "SPECULATIVE", "unconfirmed_binding"
    return "CURRENT_CONFIRMED", "current_head"


def keep(record: dict, *, entities=None, contexts=None, lifecycle=None, status=None,
         window=None) -> tuple:
    """(True, reason) when the record satisfies every supplied anchor."""
    if entities and record.get("entity") not in entities:
        return False, "entity_filtered"
    if contexts and list(record.get("contexts") or []) != list(contexts):
        return False, "context_filtered"
    if lifecycle and str(record.get("lifecycle") or "").lower() not in {
            str(item).lower() for item in lifecycle}:
        return False, "lifecycle_filtered"
    if status and str(record.get("status") or "").lower() not in {
            str(item).lower() for item in status}:
        return False, "status_filtered"
    if window is not None and temporal.intersects(temporal.span(record), window) is not True:
        return False, "window_miss"
    return True, "kept"


def apply(rows: list[dict], **anchors) -> tuple:
    """Filter candidates before ranking; report what each filter removed, never silently."""
    kept, dropped = [], {}
    for row in rows:
        ok, reason = keep(row, **anchors)
        if ok:
            kept.append(row)
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept, dropped


__all__ = ["FLAGS", "enabled", "classify", "keep", "apply"]
