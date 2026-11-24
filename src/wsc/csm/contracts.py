"""CSM contracts. Semantic choices belong to the caller's model, never here.

The only semantic vocabulary this module fixes is the shallow type tree from the
design (§5.1) plus the closed sets the storage layer can actually enforce.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..contracts import WSCError, digest, encode, require
from . import redact


class CSMError(WSCError):
    """A neutral, machine-readable CSM execution result."""


def require(condition: bool, reason: str) -> None:  # noqa: F811 - CSM calls fail as CSMError
    """Every rejected CSM precondition surfaces as ``CSMError``, never a bare WSCError."""
    if not condition:
        raise CSMError(reason)


# Shallow semantic type tree: child -> parent. None means the parent is "Memory".
# A subtype may be narrowed from its parent with evidence, never swapped sideways.
TYPE_TREE = {
    "Fact": None,
    "Preference": None,
    "Commitment": None,
    "Intention": "Commitment",
    "Plan": "Commitment",
    "Task": "Commitment",
    "Relationship": None,
}

# Memory lifecycle, deliberately separate from domain status and from the fact value.
LIFECYCLES = ("open", "closed")

# Identity routing results (§4.3). LINK/REINTERPRET are not in the minimal slice.
INTENTS = ("auto", "create", "update", "enrich")

# Retrieval result classes (§13.4).
CURRENT_CONFIRMED = "CURRENT_CONFIRMED"
HISTORICAL = "HISTORICAL"
UNKNOWN = "UNKNOWN"

RULE_VERSION = "csm-v2"

PROPERTY_KINDS = ("state", "event")


def normalize(anchor: str, *, field: str = "anchor") -> str:
    """One canonical form per anchor so identity matching never depends on casing."""
    require(isinstance(anchor, str), f"{field}_invalid")
    text = " ".join(anchor.split()).casefold()
    require(bool(text), f"{field}_missing")
    return text


def _part(value: str) -> str:
    return "_".join(normalize(value).replace(":", "_").replace("@", "_").split())


def anchors(values, *, field: str) -> tuple[str, ...]:
    """Normalized, order-stable, duplicate-free anchor tuple."""
    require(isinstance(values, (list, tuple, set)), f"{field}_invalid")
    out = []
    for value in values:
        item = normalize(value, field=field)
        if item not in out:
            out.append(item)
    return tuple(sorted(out))


def memory_id_for(entity: str, property_ref: str, scope: str = "entity") -> str:
    """Readable identity label fixed at creation; the property id does not change."""
    head = f"{_part(entity)}:{_part(property_ref)}"
    return head + ("" if scope in ("", "entity") else "@" + _part(scope))


IDENTITY_KEY_RULE = "entity+property+scope"


def identity_key(entity: str, property_ref: str, scope: str = "entity") -> str:
    """Identity key = entity + engine-owned property id + scope, nothing else.

    The property id and the scope are allocated by the engine. A state property lives at
    the entity scope and updates in place; an event property lives at its source event's
    scope, so two different observations can never overwrite each other.
    """
    return digest({"entity": _part(entity), "property": _part(property_ref),
                   "scope": _part(scope or "entity"), "rule": IDENTITY_KEY_RULE})


@dataclass(frozen=True)
class Event:
    """An observed source event. Appending is idempotent per id."""
    id: str
    source_type: str
    payload: Any
    source_ref: str | None = None
    observed_at: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class MemoryCandidate:
    """One atomic memory proposed by the caller, carrying its own evidence.

    The component never invents entity, slot, value or evidence; it only decides
    which identity the proposal binds to and whether the transition is legal.
    """
    entity: str
    slot: str
    value: Any
    semantic_type: str = "Fact"
    contexts: tuple[str, ...] = ()
    property_kind: str | None = None
    scope: str | None = None
    topics: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    status: str | None = None
    lifecycle: str = "open"
    source_ids: tuple[str, ...] = ()
    event_group: str | None = None
    intent: str = "auto"
    expected_revision: int | None = None
    valid_from: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MemoryQuery:
    """Deterministic lookup over identity anchors; ``text`` only orders the anchor scope.

    Without text the order is the anchor's own event-time order, so a lookup is stable.
    ``scope_chain`` widens a branch lookup to its repository and then the entity level;
    the most specific state definition wins. ``at_commit`` is an as-of anchor resolved
    from an ingested commit event, never a guess.
    """
    entity: str | None = None
    slot: str | None = None
    topics: tuple[str, ...] = ()
    scope: str | None = None
    scope_chain: bool = False
    valid_at: str | None = None
    at_commit: str | None = None
    include_history: bool = False
    limit: int = 20
    text: str | None = None
    with_evidence: bool = True


def validate_event(event: Event) -> dict:
    require(isinstance(event, Event), "event_invalid")
    require(isinstance(event.id, str) and bool(event.id.strip()), "event_id_missing")
    require(isinstance(event.source_type, str) and bool(event.source_type.strip()),
            "event_source_type_missing")
    require(event.source_ref is None or isinstance(event.source_ref, str), "event_source_ref_invalid")
    require(event.observed_at is None or isinstance(event.observed_at, str), "event_observed_at_invalid")
    require(event.metadata is None or isinstance(event.metadata, dict), "event_metadata_invalid")
    clean_payload, payload_hits = redact.payload(event.payload)
    clean_meta, meta_hits = redact.payload(event.metadata or {})
    try:
        payload = encode(clean_payload)
    except (TypeError, ValueError):
        raise CSMError("event_payload_not_serializable")
    return {"id": event.id, "source_type": event.source_type, "payload": clean_payload,
            "payload_text": payload, "source_ref": event.source_ref,
            "observed_at": validate_instant(event.observed_at, field="event_observed_at"),
            "metadata": clean_meta, "redacted": payload_hits + meta_hits}


def validate_candidate(candidate: MemoryCandidate) -> dict:
    require(isinstance(candidate, MemoryCandidate), "candidate_invalid")
    require(candidate.semantic_type in TYPE_TREE, "semantic_type_unknown")
    require(candidate.lifecycle in LIFECYCLES, "lifecycle_unknown")
    require(candidate.intent in INTENTS, "intent_unknown")
    require(candidate.property_kind is None or candidate.property_kind in PROPERTY_KINDS,
            "property_kind_invalid")
    require(candidate.scope is None or (isinstance(candidate.scope, str)
                                        and bool(candidate.scope.strip())),
            "scope_invalid")
    require(candidate.status is None
            or (isinstance(candidate.status, str) and bool(candidate.status.strip())),
            "domain_status_invalid")
    revision = candidate.expected_revision
    require(revision is None
            or (isinstance(revision, int) and not isinstance(revision, bool) and revision > 0),
            "expected_revision_invalid")
    require(candidate.event_group is None or isinstance(candidate.event_group, str),
            "event_group_invalid")
    clean_value, value_hits = redact.payload(candidate.value)
    try:
        encode(clean_value)
    except (TypeError, ValueError):
        raise CSMError("candidate_value_not_serializable")
    sources = candidate.source_ids
    require(isinstance(sources, (list, tuple)) and bool(sources), "evidence_source_missing")
    require(all(isinstance(s, str) and bool(s.strip()) for s in sources), "evidence_source_invalid")
    symbols = anchors(candidate.symbols, field="symbol")
    require(len(symbols) <= 64 and all(len(item) <= 64 for item in symbols), "symbol_invalid")
    return {"entity": normalize(candidate.entity, field="entity"),
            "slot": normalize(candidate.slot, field="slot"),
            "value": clean_value, "redacted": value_hits,
            "semantic_type": candidate.semantic_type,
            "contexts": anchors(candidate.contexts, field="context"),
            "property_kind": candidate.property_kind,
            "scope": None if candidate.scope is None else candidate.scope.strip(),
            "topics": anchors(candidate.topics, field="topic"),
            "symbols": symbols,
            "status": None if candidate.status is None else candidate.status.strip(),
            "lifecycle": candidate.lifecycle,
            "source_ids": tuple(dict.fromkeys(sources)),
            "event_group": candidate.event_group,
            "intent": candidate.intent,
            "expected_revision": revision,
            "valid_from": validate_instant(candidate.valid_from, field="valid_from"),
            "reason": candidate.reason}


def validate_instant(value, *, field: str) -> str | None:
    """Valid-time anchors are ISO instants; a non-instant is a caller error, not a guess."""
    if value is None:
        return None
    require(isinstance(value, str) and bool(value.strip()), f"{field}_invalid")
    try:
        parse_instant(value)
    except ValueError:
        raise CSMError(f"{field}_invalid")
    return value.strip()


def parse_instant(value: str) -> datetime:
    """Compare instants as instants, not as strings: offsets must not change ordering."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate_query(query: MemoryQuery) -> dict:
    require(isinstance(query, MemoryQuery), "query_invalid")
    entity = None if query.entity is None else normalize(query.entity, field="entity")
    slot = None if query.slot is None else normalize(query.slot, field="slot")
    require(entity is not None or slot is not None or bool(query.topics), "query_empty")
    require(isinstance(query.limit, int) and not isinstance(query.limit, bool) and query.limit > 0,
            "query_limit_invalid")
    text = None if query.text is None else (str(query.text).strip() or None)
    scope = None if query.scope is None else str(query.scope).strip()
    require(scope is None or bool(scope), "scope_invalid")
    require(not (query.scope_chain and scope is None), "scope_chain_without_scope")
    at_commit = None if query.at_commit is None else str(query.at_commit).strip()
    require(at_commit is None or bool(at_commit), "at_commit_invalid")
    require(not (at_commit and query.valid_at), "query_time_ambiguous")
    return {"entity": entity, "slot": slot,
            "topics": anchors(query.topics, field="topic"),
            "scope": scope, "scope_chain": bool(query.scope_chain),
            "valid_at": validate_instant(query.valid_at, field="valid_at"),
            "at_commit": at_commit,
            "include_history": bool(query.include_history),
            "limit": query.limit,
            "text": text,
            "with_evidence": bool(query.with_evidence)}
