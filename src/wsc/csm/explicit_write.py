"""Opt-in caller-declared identity attribution and value operations.

Source integrity is checked here; semantic support remains a caller assertion.
Mappings are local to one write, never entity aliases or a migration of old rows.
"""
from __future__ import annotations

import json

from ..contracts import digest, encode
from . import domain, identity, pending, state
from .contracts import MemoryCandidate, require, validate_candidate

OPERATIONS = ("create", "replace", "set_add", "set_remove", "observe")
POLICY = "caller-declared-write-v1"


def _sources(db, ids):
    require(isinstance(ids, (list, tuple)), "binding_sources_invalid")
    require(all(isinstance(item, str) and item.strip() for item in ids),
            "evidence_source_invalid")
    for source_id in dict.fromkeys(ids):
        row = db.execute("SELECT data, digest FROM events WHERE id = ?", (source_id,)).fetchone()
        require(row is not None, "evidence_source_unknown")
        require(digest(json.loads(row["data"])) == row["digest"], "evidence_source_digest_mismatch")


def _set(value):
    require(isinstance(value, list), "collection_value_not_list")
    keys = [encode(item) for item in value]
    require(len(keys) == len(set(keys)), "collection_duplicate_member")
    return keys


def _defer(db, csm, data, request, missing, *, producer, recorded_at, parked=None):
    if parked is not None:
        return {"operation": "DEFER", "pending_id": parked["pending_id"],
                "changed": False, "missing_conditions": missing, "policy": POLICY}
    key = "pnd_" + digest({"namespace": csm.store.namespace, "type": "explicit_write",
                           "candidate": data, "request": request})[:24]
    item = {"pending_id": key, "pending_type": "explicit_write", "status": "pending",
            "reason": "explicit_write_incomplete", "entity": data["entity"],
            "slot": data["slot"], "contexts": list(data["contexts"]), "candidate": data,
            "request": request, "semantic_payload": {k: data[k] for k in
                ("value", "status", "lifecycle", "semantic_type", "topics")},
            "source_refs": list(dict.fromkeys([*data["source_ids"], *request["binding_source_ids"]])),
            "candidate_targets": [request["target_memory_id"]] if request["target_memory_id"] else [],
            "missing_conditions": missing, "producer": producer, "created_at": recorded_at,
            "resolved_at": None, "memory_id": None}
    stored = pending._insert(db, key, "explicit_write", item)
    return {"operation": "DEFER", "pending_id": key, "changed": stored["changed"],
            "missing_conditions": missing, "policy": POLICY}


def _apply(db, csm, candidate, *, operation, target_memory_id, binding_source_ids,
           producer, parked=None):
    data = validate_candidate(candidate)
    require(data["intent"] == "auto" and data["target_memory_id"] is None,
            "explicit_write_candidate_intent_conflict")
    require(operation is None or operation in OPERATIONS, "value_operation_unknown")
    require(target_memory_id is None or
            (isinstance(target_memory_id, str) and bool(target_memory_id.strip())),
            "target_memory_id_invalid")
    _sources(db, data["source_ids"])
    _sources(db, binding_source_ids)
    domain.validate_status(data["semantic_type"], data["status"])
    request = {"operation": operation, "target_memory_id": target_memory_id,
               "binding_source_ids": list(dict.fromkeys(binding_source_ids))}
    now = csm.clock()
    if operation == "observe":
        require(target_memory_id is None and not binding_source_ids
                and data["expected_revision"] is None, "observation_state_target_present")
        return {"operation": "OBSERVE", "changed": False, "state_changed": False,
                "source_refs": list(data["source_ids"]), "candidate": data, "policy": POLICY}

    owner = identity.live(db, target_memory_id) if target_memory_id else None
    previous = state.head(db, owner["memory_id"]) if owner else None
    # Existing type/status/CAS rules also apply to incomplete requests with a target.
    if owner:
        state.validate_transition(previous, data)
    missing = []
    if operation is None:
        missing.append("value_operation")
    elif operation == "create":
        require(target_memory_id is None and not binding_source_ids,
                "create_identity_binding_present")
        require(data["expected_revision"] is None, "create_expected_revision_present")
    else:
        if owner is None:
            missing.append("target_memory_id")
        if not binding_source_ids:
            missing.append("identity_binding_sources")
        if data["expected_revision"] is None:
            missing.append("expected_revision")
    if missing:
        return _defer(db, csm, data, request, missing, producer=producer,
                      recorded_at=now, parked=parked)

    original = dict(data)
    if operation == "create":
        # Independent facts need caller-declared distinguishing anchors, not slot counters.
        require(identity.route(db, data)["operation"] == "CREATE", "create_identity_exists")
        data = {**data, "intent": "create"}
    else:
        require(previous is not None, "memory_revision_missing")
        data = {**data, "entity": owner["entity"], "slot": owner["slot"],
                "contexts": tuple(owner["contexts"]), "intent": "update"}
        if operation in ("set_add", "set_remove"):
            require(previous["semantic_type"] == data["semantic_type"] == "Fact"
                    and previous["lifecycle"] == data["lifecycle"] == "open",
                    "collection_state_scope")
            old_keys, delta_keys = _set(previous["value"]), _set(data["value"])
            if operation == "set_add":
                value = previous["value"] + [v for k, v in zip(delta_keys, data["value"])
                                             if k not in old_keys]
            else:
                value = [v for k, v in zip(old_keys, previous["value"]) if k not in delta_keys]
            # The resulting collection depends on its base and the explicit delta.
            refs = tuple(dict.fromkeys([*previous["source_refs"], *data["source_ids"]]))
            _sources(db, refs)
            data = {**data, "value": value, "source_ids": refs}
        # Binding evidence is part of the committed attribution provenance as well.
        data = {**data, "source_ids": tuple(dict.fromkeys(
            [*data["source_ids"], *binding_source_ids]))}
    result = csm._remember_one(db, data, producer=producer)
    require(result["operation"] != "DEFER", "explicit_write_routing_conflict")
    if owner:
        require(result["memory_id"] == owner["memory_id"], "explicit_write_routing_conflict")
    receipt = {"policy": POLICY, "value_operation": operation, "candidate": original,
               "requested_target": target_memory_id, "memory_id": result["memory_id"],
               "revision": result["revision"], "binding_source_ids": list(binding_source_ids),
               "attribution": "caller_declared", "semantic_support": "not_verified",
               "completeness": "not_established", "producer": producer}
    db.execute("INSERT INTO identity_changes(memory_id, kind, recorded_at, data) VALUES(?, ?, ?, ?)",
               (result["memory_id"], "explicit_write", now, encode(receipt)))
    return {**result, "write_receipt": receipt, "policy": POLICY}


def remember(csm, candidate: MemoryCandidate, *, operation=None, target_memory_id=None,
             binding_source_ids=(), producer="model"):
    with csm.store.transaction() as db:
        return _apply(db, csm, candidate, operation=operation, target_memory_id=target_memory_id,
                      binding_source_ids=binding_source_ids, producer=producer)


def resolve(csm, pending_id, *, operation=None, target_memory_id=None,
            binding_source_ids=(), expected_revision=None, producer="model"):
    with csm.store.transaction() as db:
        item = pending.get(db, pending_id)
        require(item["pending_type"] == "explicit_write", "pending_type_mismatch")
        require(item["status"] == "pending", "pending_already_settled")
        request = item["request"]
        fields = dict(item["candidate"])
        if expected_revision is not None:
            fields["expected_revision"] = expected_revision
        result = _apply(db, csm, MemoryCandidate(**fields),
                        operation=operation if operation is not None else request["operation"],
                        target_memory_id=(target_memory_id if target_memory_id is not None
                                          else request["target_memory_id"]),
                        binding_source_ids=binding_source_ids or request["binding_source_ids"],
                        producer=producer, parked=item)
        if result["operation"] != "DEFER":
            pending.settle(db, pending_id, memory_id=result.get("memory_id"),
                           recorded_at=csm.clock())
        return {**result, "pending_id": pending_id}
