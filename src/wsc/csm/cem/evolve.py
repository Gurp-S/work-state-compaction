"""Tree Evolution Controller (§12.3): one explicit pass, no background loop.

The controller performs only the structural operations V1 trusts automatically:
CREATE_ENTITY, MOUNT and PROMOTE, plus resolving a parked mount whose candidate set has
collapsed to exactly one active node. Everything else stays a proposal for the caller;
a refused action is reported with its code, never retried in the background.
"""
from __future__ import annotations

import json

from ..contracts import CSMError
from . import pending as pendings
from . import tree


def _live_identities(db) -> list[dict]:
    return [json.loads(row["data"]) for row in
            db.execute("SELECT data FROM identities ORDER BY memory_id")]


def _mounted(db, memory_id: str) -> bool:
    return db.execute("SELECT 1 FROM tree_mounts WHERE memory_id = ? LIMIT 1",
                      (memory_id,)).fetchone() is not None


def _active_nodes(service, candidates) -> list[str]:
    active = []
    with service.store.connect() as db:
        for node_id in candidates:
            row = db.execute("SELECT data FROM tree_nodes WHERE node_id = ?",
                             (node_id,)).fetchone()
            if row is not None and json.loads(row["data"])["status"] == "active":
                active.append(node_id)
    return active


def _code(error: CSMError) -> str:
    return getattr(error, "code", str(error))


def _entity_node(service, entity: str, evidence) -> dict:
    """Reuse the entity node that already anchors this entity; create one only if absent."""
    with service.store.connect() as db:
        for item in tree.nodes(db, status="active", limit=10000):
            contract = item.get("contract") or {}
            if item["node_type"] == "entity" and contract.get("entity_anchor") == entity:
                return item
    return service.create_node(name=entity, node_type="entity", entity_anchor=entity,
                               evidence=evidence)


def evolve(service, *, producer: str = "controller", promote_threshold: int = 2,
           window_seconds: float | None = None, limit: int = 100) -> dict:
    actions: list[dict] = []
    with service.store.connect() as db:
        parked = [item for item in pendings.listing(db, limit=1000)
                  if item["pending_type"] == "mount"]
        waiting = [item for item in _live_identities(db)
                   if not item.get("merged_into") and not _mounted(db, item["memory_id"])]

    # 1. A mount parked while several nodes were plausible becomes decidable once only
    #    one candidate is still active; ambiguity is left parked.
    for item in parked[:limit]:
        active = _active_nodes(service, item.get("candidate_targets") or [])
        if len(active) != 1:
            continue
        try:
            resolved = service.resolve_mount(item["pending_id"], node_id=active[0],
                                             producer=producer)
        except CSMError as error:
            actions.append({"action": "resolve_mount", "pending_id": item["pending_id"],
                            "changed": False, "skipped": _code(error)})
            continue
        actions.append({"action": "resolve_mount", "pending_id": item["pending_id"],
                        "node_id": active[0], "changed": resolved.get("changed", False)})

    # 2. An identity with evidence but no mount gets its entity node; the node is the
    #    index, the memory keeps its own revision.
    for item in waiting[:limit]:
        if not item.get("identity_evidence"):
            actions.append({"action": "mount", "memory_id": item["memory_id"],
                            "changed": False, "skipped": "tree_scope_evidence_missing"})
            continue
        try:
            node = _entity_node(service, item["entity"], item["identity_evidence"][:1])
            mounted = service.mount(item["memory_id"], node_id=node["node_id"],
                                    producer=producer)
        except CSMError as error:
            actions.append({"action": "mount", "memory_id": item["memory_id"],
                            "changed": False, "skipped": _code(error)})
            continue
        actions.append({"action": "mount", "memory_id": item["memory_id"],
                        "node_id": node["node_id"], "changed": mounted.get("changed", False)})

    # 3. Candidate organization nodes are published only when coverage, contract and
    #    evidence agree; a refusal is reported, not forced.
    with service.store.connect() as db:
        candidates = tree.nodes(db, status="candidate", limit=10000)
    for item in candidates[:limit]:
        try:
            promoted = service.promote(item["node_id"], evidence=item.get("evidence") or (),
                                       threshold=promote_threshold,
                                       window_seconds=window_seconds, producer=producer)
        except CSMError as error:
            actions.append({"action": "promote", "node_id": item["node_id"],
                            "changed": False, "skipped": _code(error)})
            continue
        actions.append({"action": "promote", "node_id": item["node_id"],
                        "changed": promoted.get("changed", False)})

    counts: dict[str, int] = {}
    for item in actions:
        key = f"{item['action']}:{'changed' if item['changed'] else 'skipped'}"
        counts[key] = counts.get(key, 0) + 1
    return {"actions": actions, "counts": counts,
            "changed": any(item["changed"] for item in actions)}


__all__ = ["evolve"]
