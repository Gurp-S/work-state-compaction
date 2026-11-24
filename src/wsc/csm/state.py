"""Append-only state with an explicit observed-time timeline.

Revision, head and projection commit together. Eligibility is decided by ``valid_from``
(the source event's observed time); ``recorded_at`` never participates in as-of.
"""
from __future__ import annotations

import json

from ..contracts import encode
from . import index
from .contracts import CSMError, RULE_VERSION, TYPE_TREE, require


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
    items = revisions(db, memory_id)
    out = []
    for position, item in enumerate(items):
        valid_to = items[position + 1]["valid_from"] if position + 1 < len(items) else None
        out.append({**item, "valid_to": valid_to})
    return out


def _narrowing_allowed(previous: str, current: str) -> bool:
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


def validate_transition(previous: dict | None, candidate: dict) -> None:
    require(previous is None or _narrowing_allowed(previous["semantic_type"],
                                                  candidate["semantic_type"]),
            "semantic_type_conflict")
    expected = candidate["expected_revision"]
    if expected is not None:
        actual = 0 if previous is None else previous["revision"]
        if expected != actual:
            raise CSMError("memory_revision_conflict")


def append(db, identity: dict, candidate: dict, *, producer: str, recorded_at: str,
           effective_at: str | None, topics: list[str], symbols: list[str] | None = None,
           commit: str | None = None) -> dict:
    memory_id = identity["memory_id"]
    previous = head(db, memory_id)
    validate_transition(previous, candidate)
    operation = _operation(previous, candidate)
    if operation is None:
        index.update(db, memory_id, entity=identity["entity"], property_name=identity["slot"],
                     value=previous["value"], revision=previous["revision"], topics=topics)
        index.update_symbols(db, memory_id, symbols, previous["revision"])
        return {"memory_id": memory_id, "revision": previous["revision"], "changed": False,
                "operation": "none", "reason": "duplicate_observation"}
    number = 1 if previous is None else previous["revision"] + 1
    valid_from = candidate.get("valid_from") or effective_at or recorded_at
    record = {"memory_id": memory_id, "revision": number,
              "previous": None if previous is None else previous["revision"],
              "operation": operation, "semantic_type": candidate["semantic_type"],
              "value": candidate["value"], "status": candidate["status"],
              "lifecycle": candidate["lifecycle"], "source_refs": list(candidate["source_ids"]),
              "event_group": candidate["event_group"], "effective_at": effective_at,
              "recorded_at": recorded_at, "observed_at": effective_at or valid_from,
              "producer": producer, "rule_version": RULE_VERSION, "valid_from": valid_from}
    if candidate.get("certainty") is not None:
        record["certainty"] = candidate["certainty"]
    if commit:
        record["commit"] = commit
    db.execute("INSERT INTO revisions(memory_id, revision, data, valid_from, effective_at, "
               "observed_at) VALUES(?, ?, ?, ?, ?, ?)",
               (memory_id, number, json.dumps(record, sort_keys=True, ensure_ascii=False),
                valid_from, effective_at, record["observed_at"]))
    db.execute("INSERT INTO heads(memory_id, current_revision, projection_version) VALUES(?, ?, ?) "
               "ON CONFLICT(memory_id) DO UPDATE SET current_revision = excluded.current_revision, "
               "projection_version = excluded.projection_version",
               (memory_id, number, number))
    if identity["semantic_type"] != candidate["semantic_type"]:
        identity["semantic_type"] = candidate["semantic_type"]
        db.execute("UPDATE identities SET semantic_type = ?, data = ? WHERE memory_id = ?",
                   (identity["semantic_type"],
                    json.dumps(identity, sort_keys=True, ensure_ascii=False), memory_id))
    index.update(db, memory_id, entity=identity["entity"], property_name=identity["slot"],
                 value=record["value"], revision=number, topics=topics)
    index.update_symbols(db, memory_id, symbols, number)
    return {"memory_id": memory_id, "revision": number, "changed": True,
            "operation": operation,
            **({"commit": commit} if commit else {})}


__all__ = ["head", "revision", "revisions", "timeline", "validate_transition", "append"]
