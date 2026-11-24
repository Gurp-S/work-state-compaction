"""The benchmark's answer input keeps the engine's evidence packet intact."""
import json
import os
# Kept import-free so the disabled adapter can replay a frozen older core.
POLICY = "structured-source-fusion-v3"
SOURCE_POLICY = "source-evidence-v2"


def mode():
    value = os.environ.get("WSC_CSM_EVIDENCE_PIPELINE", "fusion").strip().lower()
    if value in {"0", "false", "off", "legacy"}:
        return "legacy"
    if value in {"1", "true", "on", "fusion"}:
        return "fusion"
    if value == "source-only":
        return value
    raise ValueError("WSC_CSM_EVIDENCE_PIPELINE must be fusion, legacy/0, or source-only")


def source_only():
    return mode() == "source-only"


def policy():
    return SOURCE_POLICY if source_only() else POLICY


def supplement_prefilter():
    return os.environ.get("WSC_CSM_SUPPLEMENT_PREFILTER", "0").strip().lower() in {"1", "true", "on"}


def configuration():
    return {"mode": mode(), "policy": policy() if enabled() else "legacy",
        "primary_budget": "unchanged legacy retrieval configuration",
        "supplement_max_chars": int(os.environ.get("WSC_CSM_CONTEXT_CHARS", "4000")) if enabled() else 0,
        "supplement_max_items": int(os.environ.get("WSC_CSM_SOURCE_ITEMS", "6")) if enabled() else 0,
        "budget_scope": "supplement_only", "supplement_prefilter": supplement_prefilter()}


def validate_config(retrieval_flags=()):
    selected = mode()
    if selected == "source-only":
        ignored = [name for name in retrieval_flags
                   if os.environ.get(name, "0").strip().lower() not in {"0", "false", "off", ""}]
        if ignored:
            raise ValueError("source-only would bypass configured retrieval features: " + ", ".join(ignored))
    if selected != "legacy":
        if int(os.environ.get("WSC_CSM_CONTEXT_CHARS", "4000")) < 256:
            raise ValueError("Supplement budget must be at least 256 characters")
        if int(os.environ.get("WSC_CSM_SOURCE_ITEMS", "6")) < 1:
            raise ValueError("Supplement item limit must be positive")


def enabled():
    return mode() != "legacy"


class EvidenceRows(list):
    def __init__(self, packet):
        super().__init__(packet["items"])
        self.packet = packet


class FusedRows(EvidenceRows):
    """Primary winners are immutable to supplemental ranking and budgeting."""
    def __init__(self, primary, supplement):
        self.primary = list(primary)
        self.supplement = supplement
        super().__init__({**supplement, "items": self.primary + supplement["items"]})


def candidate_rows(rows):
    """Bridge the legacy row interface without turning proposals into facts."""
    for row in rows:
        if row.get("pending_id"):
            yield {**row, "memory_id": row["pending_id"], "record_type": "pending",
                   "value": (row.get("proposed") or {}).get("value", row.get("value")),
                   "classification": "PENDING_BINDING", "confirmed": False}
        elif row.get("memory_id"):
            yield row
        else:
            raise ValueError("Retrieval returned a row without memory or pending identity")


def fuse(service, question, primary, *, until=None):
    if not enabled():
        return primary
    if source_only():
        raise ValueError("fuse requires the fusion backend, not source-only")
    primary_ids = {r.get("memory_id") for r in primary}
    eligibility = {}
    if supplement_prefilter():
        eligibility = {"record_types": ("source_event", "pending"),
                       "exclude_ids": tuple(sorted(item for item in primary_ids if item))}
    supplement = service.recall_evidence(question,
        limit=int(os.environ.get("WSC_CSM_SOURCE_ITEMS", "6")),
        max_chars=int(os.environ.get("WSC_CSM_CONTEXT_CHARS", "4000")), until=until,
        **eligibility)
    # Do not duplicate the legacy state lane or expose database validity times
    # as event dates. Raw observations and unresolved proposals supplement it.
    supplement = {**supplement, "items": [r for r in supplement["items"]
        if r.get("record_type") in {"source_event", "pending"}
        and r.get("memory_id") not in primary_ids]}
    return FusedRows(primary, supplement)


def render_fused(rows, rendered_primary):
    primary = json.loads(rendered_primary)
    items = primary + rows.supplement["items"]
    return json.dumps({"policy": POLICY, "items": items,
        "primary_count": len(primary), "primary_preserved": True,
        "state_scope": "identity_revisions_not_world_confirmation",
        "completeness": "not_established",
        "supplement": {**{key: rows.supplement.get(key) for key in
            ("policy", "max_chars", "max_items", "truncated", "omitted")},
            "published_items": len(rows.supplement["items"]),
            "published_items_chars": len(json.dumps(rows.supplement["items"], ensure_ascii=False, separators=(",", ":")))},
        "budget_scope": "supplement_only; primary uses existing retrieval budget"},
        ensure_ascii=False, separators=(",", ":"))


def retrieve(service, question, *, limit, until=None):
    return EvidenceRows(service.recall_evidence(question, limit=limit,
        max_chars=int(os.environ.get("WSC_CSM_CONTEXT_CHARS", "4000")), until=until))


def render(rows):
    return json.dumps(rows.packet, ensure_ascii=False, separators=(",", ":"))
