"""Unified state engine: revisions are appended, never overwritten.

One transition produces Revision + Head + Projection inside the caller's transaction,
so a failure cannot leave a partially committed state (§A02/A03).
"""
from __future__ import annotations

import json

from ..contracts import encode
from .contracts import require
from . import domain
from .contracts import CSMError, RULE_VERSION, TYPE_TREE, parse_instant
from .projection_store import put as put_projection


def head(db, memory_id: str) -> dict | None:
    row = db.execute("SELECT current_revision FROM heads WHERE memory_id = ?",
                     (memory_id,)).fetchone()
    if row is None:
        return None
    return revision(db, memory_id, row["current_revision"])


def revision(db, memory_id: str, number: int) -> dict | None:
    row = db.execute("SELECT data FROM revisions WHERE memory_id = ? AND revision = ?",
                     (memory_id, number)).fetchone()
    return None if row is None else json.loads(row["data"])


def revisions(db, memory_id: str) -> list[dict]:
    return [json.loads(row["data"]) for row in
            db.execute("SELECT data FROM revisions WHERE memory_id = ? ORDER BY revision",
                       (memory_id,))]


def timeline(db, memory_id: str) -> list[dict]:
    """Revisions with their validity interval closed by the next revision's valid_from.

    The interval is derived on read, so a later revision never rewrites an earlier one.
    """
    items = revisions(db, memory_id)
    out = []
    for index, item in enumerate(items):
        valid_to = items[index + 1]["valid_from"] if index + 1 < len(items) else None
        out.append({**item, "valid_to": valid_to})
    return out


def at(db, memory_id: str, instant: str) -> dict | None:
    """The revision whose valid interval contains the instant, or None: no invention."""
    target = parse_instant(instant)
    chosen = None
    for item in timeline(db, memory_id):
        start = parse_instant(item["valid_from"])
        end = None if item["valid_to"] is None else parse_instant(item["valid_to"])
        if start <= target and (end is None or target < end):
            chosen = item
    return chosen


def _narrowing_allowed(previous: str, current: str) -> bool:
    """A type may be narrowed to its own subtype; sideways swaps are rejected."""
    return current == previous or TYPE_TREE.get(current) == previous


def _operation(previous: dict | None, candidate: dict) -> str | None:
    if previous is None:
        return "create"
    if (encode(previous["value"]) != encode(candidate["value"])
            or previous["status"] != candidate["status"]
            or previous.get("certainty") != candidate.get("certainty")):
        return "update"
    if previous["semantic_type"] != candidate["semantic_type"]:
        return "narrow"
    if previous["lifecycle"] != candidate["lifecycle"]:
        return "close" if candidate["lifecycle"] == "closed" else "reopen"
    return None


def projection_payload(identity: dict, current: dict, topics: list[str]) -> dict:
    """The current-state view, derivable from the identity plus its head revision."""
    return {"memory_id": identity["memory_id"], "entity": identity["entity"],
            "slot": identity["slot"], "contexts": identity["contexts"],
            "semantic_type": current["semantic_type"], "topics": topics,
            "value": current["value"], "status": current["status"],
            "lifecycle": current["lifecycle"], "revision": current["revision"],
            "source_refs": current["source_refs"], "effective_at": current["effective_at"],
            "recorded_at": current["recorded_at"], "valid_from": current.get("valid_from"),
            **({"certainty": current["certainty"]} if "certainty" in current else {})}


def validate_transition(previous: dict | None, candidate: dict) -> None:
    """Read-only preconditions shared by committed and deferred observations."""
    require(previous is None or _narrowing_allowed(previous["semantic_type"],
                                                  candidate["semantic_type"]),
            "semantic_type_conflict")
    previous_status = (None if previous is None
                       or previous["semantic_type"] != candidate["semantic_type"]
                       else previous["status"])
    domain.validate_status(candidate["semantic_type"], candidate["status"], previous_status)
    expected = candidate["expected_revision"]
    if expected is not None:
        actual = 0 if previous is None else previous["revision"]
        if expected != actual:
            raise CSMError("memory_revision_conflict")


def append(db, identity: dict, candidate: dict, *, producer: str, recorded_at: str,
           effective_at: str | None, topics: list[str]) -> dict:
    memory_id = identity["memory_id"]
    previous = head(db, memory_id)
    validate_transition(previous, candidate)
    operation = _operation(previous, candidate)
    if operation is None:
        payload = projection_payload(identity, previous, topics)
        put_projection(db, payload)
        return {"memory_id": memory_id, "revision": previous["revision"], "changed": False,
                "operation": "none", "reason": "duplicate_observation",
                "memory": payload}
    number = 1 if previous is None else previous["revision"] + 1
    record = {"memory_id": memory_id, "revision": number,
              "previous": None if previous is None else previous["revision"],
              "operation": operation, "semantic_type": candidate["semantic_type"],
              "value": candidate["value"], "status": candidate["status"],
              "lifecycle": candidate["lifecycle"], "source_refs": list(candidate["source_ids"]),
              "event_group": candidate["event_group"], "effective_at": effective_at,
              "recorded_at": recorded_at, "producer": producer, "rule_version": RULE_VERSION,
              "valid_from": candidate.get("valid_from") or effective_at or recorded_at}
    if candidate.get("certainty") is not None:
        record["certainty"] = candidate["certainty"]
    db.execute("INSERT INTO revisions(memory_id, revision, data) VALUES(?, ?, ?)",
               (memory_id, number, json.dumps(record, sort_keys=True, ensure_ascii=False)))
    db.execute("INSERT INTO heads(memory_id, current_revision, projection_version) VALUES(?, ?, ?) "
               "ON CONFLICT(memory_id) DO UPDATE SET current_revision = excluded.current_revision, "
               "projection_version = excluded.projection_version",
               (memory_id, number, number))
    if identity["semantic_type"] != candidate["semantic_type"]:
        identity["semantic_type"] = candidate["semantic_type"]
        db.execute("UPDATE identities SET semantic_type = ?, data = ? WHERE memory_id = ?",
                   (identity["semantic_type"],
                    json.dumps(identity, sort_keys=True, ensure_ascii=False), memory_id))
    payload = projection_payload(identity, record, topics)
    put_projection(db, payload)
    return {"memory_id": memory_id, "revision": number, "changed": True,
            "operation": operation, "memory": payload}
