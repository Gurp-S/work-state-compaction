"""Pending pool: an unresolved attribution is never a confirmed fact.

Three kinds share one table because all three mean the same thing to the caller — the
engine could not decide, so it stored the proposal instead of guessing:

* ``identity``      — which identity a proposal belongs to is undecidable;
* ``mount``         — which tree node a memory belongs to is undecidable;
* ``identity_operation`` — a structural fix (REKEY/MERGE) is proposed but not applied.
"""
from __future__ import annotations

import json

from ..contracts import digest
from .contracts import CSMError


def _insert(db, key: str, pending_type: str, data: dict) -> dict:
    row = db.execute("SELECT data FROM pending WHERE pending_id = ?", (key,)).fetchone()
    if row is not None:
        return {**json.loads(row["data"]), "changed": False}
    db.execute("INSERT INTO pending(pending_id, pending_type, status, entity, slot, data) "
               "VALUES(?, ?, ?, ?, ?, ?)",
               (key, pending_type, "pending", data.get("entity"), data.get("slot"),
                json.dumps(data, sort_keys=True, ensure_ascii=False)))
    return {**data, "changed": True}


def pending_id(namespace: str, candidate: dict) -> str:
    """Deterministic, so re-observing the same ambiguous proposal cannot pile up."""
    return "pnd_" + digest({"namespace": namespace, "entity": candidate["entity"],
                            "slot": candidate["slot"], "value": candidate["value"],
                            "contexts": list(candidate["contexts"]),
                            "source_ids": list(candidate["source_ids"])})[:24]


def open_pending(db, namespace: str, candidate: dict, routing: dict, *,
                 producer: str, recorded_at: str) -> dict:
    key = pending_id(namespace, candidate)
    data = {"pending_id": key, "pending_type": "identity", "status": "pending",
            "reason": routing["reason"], "entity": candidate["entity"],
            "slot": candidate["slot"], "contexts": list(candidate["contexts"]),
            "semantic_payload": {k: candidate[k] for k in
                                 ("value", "status", "lifecycle", "semantic_type", "topics")},
            "candidate_targets": routing.get("candidate_targets", []),
            "missing_conditions": routing.get("missing_conditions", []),
            "source_refs": list(candidate["source_ids"]), "producer": producer,
            "created_at": recorded_at, "resolved_at": None, "memory_id": None}
    return _insert(db, key, "identity", data)


def open_mount(db, namespace: str, memory_id: str, *, candidates, reason: str,
               missing, source_ids, producer: str, recorded_at: str) -> dict:
    """A mount that cannot be decided is parked, not attached to a plausible-looking node."""
    key = "pnd_" + digest({"namespace": namespace, "type": "mount", "memory_id": memory_id,
                           "candidates": list(candidates)})[:24]
    data = {"pending_id": key, "pending_type": "mount", "status": "pending",
            "reason": reason, "memory_id": memory_id, "entity": None, "slot": None,
            "contexts": [], "candidate_targets": list(candidates),
            "missing_conditions": list(missing), "source_refs": list(source_ids),
            "producer": producer, "created_at": recorded_at, "resolved_at": None,
            "node_id": None}
    return _insert(db, key, "mount", data)


def open_identity_operation(db, namespace: str, proposal: dict, *, producer: str,
                            recorded_at: str) -> dict:
    """A structural identity fix (rekey/merge) is stored as a proposal, never auto-applied."""
    key = "pnd_" + digest({"namespace": namespace, "type": "identity_operation",
                           "operation": proposal["operation"],
                           "memory_id": proposal.get("memory_id"),
                           "source": proposal.get("source")})[:24]
    data = {"pending_id": key, "pending_type": "identity_operation", "status": "pending",
            "reason": proposal["reason"], "operation": proposal["operation"],
            "memory_id": proposal.get("memory_id"), "source": proposal.get("source"),
            "contexts": list(proposal.get("contexts", ())),
            "entity": proposal.get("entity"), "slot": proposal.get("slot"),
            "candidate_targets": list(proposal.get("candidate_targets", ())),
            "missing_conditions": list(proposal.get("missing_conditions", ())),
            "source_refs": list(proposal.get("source_refs", ())), "producer": producer,
            "created_at": recorded_at, "resolved_at": None}
    return _insert(db, key, "identity_operation", data)


def listing(db, *, limit: int = 100, status: str = "pending",
            pending_type: str | None = None) -> list[dict]:
    if pending_type is None:
        rows = db.execute("SELECT data FROM pending WHERE status = ? ORDER BY pending_id LIMIT ?",
                          (status, limit))
    else:
        rows = db.execute("SELECT data FROM pending WHERE status = ? AND pending_type = ? "
                          "ORDER BY pending_id LIMIT ?", (status, pending_type, limit))
    return [json.loads(row["data"]) for row in rows]


def get(db, key: str) -> dict:
    row = db.execute("SELECT data FROM pending WHERE pending_id = ?", (key,)).fetchone()
    if row is None:
        raise CSMError("pending_unknown")
    return json.loads(row["data"])


def settle(db, key: str, *, memory_id: str, recorded_at: str) -> dict:
    """Bind the pending attribution to the identity that finally matched."""
    return _settle(db, key, {"memory_id": memory_id, "resolved_at": recorded_at})


def settle_mount(db, key: str, *, node_id: str, recorded_at: str) -> dict:
    """Bind a parked mount to the node the caller finally named."""
    return _settle(db, key, {"node_id": node_id, "resolved_at": recorded_at})


def _settle(db, key: str, patch: dict) -> dict:
    data = get(db, key)
    if data["status"] == "resolved":
        return {**data, "changed": False}
    data.update({"status": "resolved", **patch})
    db.execute("UPDATE pending SET status = 'resolved', data = ? WHERE pending_id = ?",
               (json.dumps(data, sort_keys=True, ensure_ascii=False), key))
    return {**data, "changed": True}
