"""CSM contracts. Semantic choices belong to the caller's model, never here.

The only semantic vocabulary this module fixes is the shallow type tree from the
design (§5.1) plus the closed sets the storage layer can actually enforce.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..contracts import WSCError, digest, encode, require


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

# §5.2 Domain status vocabulary per semantic type. An empty tuple means the type carries
# no domain status at all: the value alone is the state.
DOMAIN_STATUS = {
    "Fact": (),
    "Preference": ("active", "retired"),
    "Commitment": ("proposed", "active", "fulfilled", "violated", "cancelled"),
    "Intention": ("proposed", "active", "satisfied", "abandoned"),
    "Plan": ("proposed", "active", "completed", "cancelled"),
    "Task": ("pending", "running", "done", "failed", "cancelled"),
    "Relationship": ("active", "ended"),
}

# §5.4 Only these edges are legal. A missing pair is not a soft failure: it is refused,
# because a domain state machine that accepts any move is not a state machine.
DOMAIN_TRANSITIONS = {
    "Preference": {("active", "retired"), ("retired", "active")},
    "Commitment": {("proposed", "active"), ("active", "fulfilled"), ("active", "violated"),
                   ("active", "cancelled"), ("proposed", "cancelled")},
    "Intention": {("proposed", "active"), ("active", "satisfied"), ("active", "abandoned"),
                  ("proposed", "abandoned")},
    "Plan": {("proposed", "active"), ("active", "completed"), ("active", "cancelled"),
             ("proposed", "cancelled")},
    "Task": {("pending", "running"), ("running", "done"), ("running", "failed"),
             ("pending", "cancelled"), ("running", "cancelled")},
    "Relationship": {("active", "ended")},
}

# §9.2 Two families with deliberately different execution semantics: organization
# relations organize retrieval, dependency relations describe effect and never move state.
ORGANIZATION_RELATIONS = ("IS_A", "PART_OF", "OWNED_BY", "PRODUCES", "ABOUT")
DEPENDENCY_RELATIONS = ("CONSTRAINT", "CAUSAL", "ASSOCIATION")
RELATION_KINDS = ORGANIZATION_RELATIONS + DEPENDENCY_RELATIONS

# §6.2 Three-valued logic. UNKNOWN is not FALSE and must survive a round trip.
TRUTHS = ("TRUE", "FALSE", "UNKNOWN")

# §6.3 The resolver only proposes impact; the state engine commits state.
DEPENDENCY_EFFECTS = ("NO_EFFECT", "REVALIDATE", "INFORMATION_GAP")

TREE_NODE_TYPES = ("entity", "organization")
TREE_OP_TYPES = ("CREATE_NODE", "CREATE_ENTITY", "MOUNT", "PROMOTE", "MERGE", "SPLIT",
                 "RETIRE", "CONTRACT")

# Identity routing results (§4.3). LINK/REINTERPRET are not in the minimal slice.
INTENTS = ("auto", "create", "update", "enrich", "link", "reinterpret")

PENDING_TYPES = ("identity", "mount", "identity_operation", "explicit_write")

# Retrieval result classes (§13.4).
CURRENT_CONFIRMED = "CURRENT_CONFIRMED"
HISTORICAL = "HISTORICAL"
PENDING_BINDING = "PENDING_BINDING"
UNKNOWN = "UNKNOWN"

RULE_VERSION = "csm-v1"


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


def memory_id_for(entity: str, slot: str, contexts: tuple[str, ...]) -> str:
    """Readable identity label fixed at creation; a rekey does not rename it."""
    head = f"{_part(entity)}:{_part(slot)}"
    return head + ("@" + ",".join(_part(c) for c in sorted(contexts)) if contexts else "")


IDENTITY_KEY_RULE = "entity+slot+declared_contexts"


def identity_key(entity: str, slot: str, contexts: tuple[str, ...]) -> str:
    """Identity key = entity + slot + the declared context set, nothing else.

    Only the declared anchors take part: topics are retrieval aids, semantic type is
    versioned state, evidence is justification. Because the declared context set is
    part of the key, changing it is a rekey (or a merge) and never an in-place edit —
    see ``identity_ops``.
    """
    return digest({"entity": _part(entity), "slot": _part(slot),
                   "contexts": [_part(c) for c in sorted(contexts)],
                   "rule": IDENTITY_KEY_RULE})


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
    topics: tuple[str, ...] = ()
    status: str | None = None
    lifecycle: str = "open"
    source_ids: tuple[str, ...] = ()
    event_group: str | None = None
    intent: str = "auto"
    expected_revision: int | None = None
    valid_from: str | None = None
    target_memory_id: str | None = None
    link_kind: str | None = None
    link_object: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MemoryQuery:
    """Deterministic lookup over identity anchors, topics, tree scope and pending bindings.

    ``text`` is optional and only changes ordering inside the anchor scope: candidates are
    ranked by term overlap first, evidence count second. Without it the order is the
    evidence-count order every caller already sees, so existing lookups are unaffected.
    """
    entity: str | None = None
    slot: str | None = None
    contexts: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    node_id: str | None = None
    valid_at: str | None = None
    expand: int = 0
    relation_kinds: tuple[str, ...] = ()
    include_dependencies: bool = False
    include_history: bool = False
    include_pending: bool = True
    limit: int = 20
    text: str | None = None


def validate_event(event: Event) -> dict:
    require(isinstance(event, Event), "event_invalid")
    require(isinstance(event.id, str) and bool(event.id.strip()), "event_id_missing")
    require(isinstance(event.source_type, str) and bool(event.source_type.strip()),
            "event_source_type_missing")
    require(event.source_ref is None or isinstance(event.source_ref, str), "event_source_ref_invalid")
    require(event.observed_at is None or isinstance(event.observed_at, str), "event_observed_at_invalid")
    require(event.metadata is None or isinstance(event.metadata, dict), "event_metadata_invalid")
    try:
        payload = encode(event.payload)
    except (TypeError, ValueError):
        raise CSMError("event_payload_not_serializable")
    return {"id": event.id, "source_type": event.source_type, "payload": event.payload,
            "payload_text": payload, "source_ref": event.source_ref,
            "observed_at": validate_instant(event.observed_at, field="event_observed_at"),
            "metadata": event.metadata or {}}


def validate_candidate(candidate: MemoryCandidate) -> dict:
    require(isinstance(candidate, MemoryCandidate), "candidate_invalid")
    require(candidate.semantic_type in TYPE_TREE, "semantic_type_unknown")
    require(candidate.lifecycle in LIFECYCLES, "lifecycle_unknown")
    require(candidate.intent in INTENTS, "intent_unknown")
    require(candidate.status is None
            or (isinstance(candidate.status, str) and bool(candidate.status.strip())),
            "domain_status_invalid")
    revision = candidate.expected_revision
    require(revision is None
            or (isinstance(revision, int) and not isinstance(revision, bool) and revision > 0),
            "expected_revision_invalid")
    require(candidate.event_group is None or isinstance(candidate.event_group, str),
            "event_group_invalid")
    require(candidate.target_memory_id is None
            or (isinstance(candidate.target_memory_id, str)
                and bool(candidate.target_memory_id.strip())),
            "target_memory_id_invalid")
    if candidate.intent == "link":
        require(candidate.link_kind in RELATION_KINDS, "relation_kind_unknown")
        require(isinstance(candidate.link_object, str) and bool(candidate.link_object.strip()),
                "relation_object_missing")
    if candidate.intent == "reinterpret":
        require(bool(candidate.contexts), "reinterpret_context_missing")
        require(isinstance(candidate.reason, str) and bool(candidate.reason.strip()),
                "reinterpret_reason_missing")
    try:
        encode(candidate.value)
    except (TypeError, ValueError):
        raise CSMError("candidate_value_not_serializable")
    sources = candidate.source_ids
    require(isinstance(sources, (list, tuple)) and bool(sources), "evidence_source_missing")
    require(all(isinstance(s, str) and bool(s.strip()) for s in sources), "evidence_source_invalid")
    return {"entity": normalize(candidate.entity, field="entity"),
            "slot": normalize(candidate.slot, field="slot"),
            "value": candidate.value,
            "semantic_type": candidate.semantic_type,
            "contexts": anchors(candidate.contexts, field="context"),
            "topics": anchors(candidate.topics, field="topic"),
            "status": None if candidate.status is None else candidate.status.strip(),
            "lifecycle": candidate.lifecycle,
            "source_ids": tuple(dict.fromkeys(sources)),
            "event_group": candidate.event_group,
            "intent": candidate.intent,
            "expected_revision": revision,
            "valid_from": validate_instant(candidate.valid_from, field="valid_from"),
            "target_memory_id": candidate.target_memory_id,
            "link_kind": candidate.link_kind,
            "link_object": candidate.link_object,
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
    require(entity is not None or slot is not None or bool(query.topics)
            or query.node_id is not None, "query_empty")
    require(isinstance(query.limit, int) and not isinstance(query.limit, bool) and query.limit > 0,
            "query_limit_invalid")
    expand = query.expand
    require(isinstance(expand, int) and not isinstance(expand, bool) and 0 <= expand <= 2,
            "query_expand_invalid")
    kinds = query.relation_kinds
    require(isinstance(kinds, (list, tuple)) and all(kind in RELATION_KINDS for kind in kinds),
            "relation_kind_unknown")
    text = None if query.text is None else (str(query.text).strip() or None)
    return {"entity": entity, "slot": slot,
            "contexts": anchors(query.contexts, field="context"),
            "topics": anchors(query.topics, field="topic"),
            "node_id": query.node_id,
            "valid_at": validate_instant(query.valid_at, field="valid_at"),
            "expand": expand,
            "relation_kinds": tuple(kinds),
            "include_dependencies": bool(query.include_dependencies),
            "include_history": bool(query.include_history),
            "include_pending": bool(query.include_pending),
            "limit": query.limit,
            "text": text}
