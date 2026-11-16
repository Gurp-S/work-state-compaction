"""Progressive state tree (§10-§12): an index over memories, never a second fact store.

The tree owns structure only. Mounting a memory changes the tree revision, not the memory
revision; a node that is promoted, merged or split can reorganize retrieval without ever
rewriting a fact. Candidate nodes exist so the tree can grow before it is trusted: an
organization node is published only when coverage, contract and evidence agree.
"""
from __future__ import annotations

import json

from ..contracts import digest
from .contracts import require
from . import identity as identities
from . import pending as pendings
from .contracts import (CSMError, ORGANIZATION_RELATIONS, TREE_NODE_TYPES, TREE_OP_TYPES,
                        normalize, parse_instant)
from .store import ROOT_NODE, getmeta, setmeta


def _head(db) -> int:
    value = getmeta(db, "tree_head")
    return 0 if value is None else int(value)


def head(db) -> int:
    """Current published tree revision."""
    return _head(db)


def _publish(db, operation_type: str, *, target_refs, source_refs, payload: dict,
             recorded_at: str, status: str = "published", previous: int | None = None) -> dict:
    require(operation_type in TREE_OP_TYPES, "tree_operation_unknown")
    previous = _head(db) if previous is None else previous
    revision = previous + 1
    cursor = db.execute("INSERT INTO tree_ops(tree_revision, operation_type, status, target_refs, "
                        "source_refs, previous_revision, payload, recorded_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (revision, operation_type, status, json.dumps(list(target_refs)),
                         json.dumps(list(source_refs)), previous,
                         json.dumps(payload, sort_keys=True, ensure_ascii=False), recorded_at))
    if status == "published":
        setmeta(db, "tree_head", revision)
    return {"op_id": cursor.lastrowid, "tree_revision": revision,
            "previous_revision": previous, "operation_type": operation_type, "status": status}


def _row(db, node_id: str):
    return db.execute("SELECT data FROM tree_nodes WHERE node_id = ?", (node_id,)).fetchone()


def node(db, node_id: str) -> dict:
    row = _row(db, node_id)
    require(row is not None, "tree_node_unknown")
    return json.loads(row["data"])


def nodes(db, *, parent_id: str | None = None, status: str | None = None,
          limit: int = 1000) -> list[dict]:
    clauses, params = [], []
    if parent_id is not None:
        clauses.append("parent_id = ?")
        params.append(parent_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = "" if not clauses else " WHERE " + " AND ".join(clauses)
    rows = db.execute(f"SELECT data FROM tree_nodes{where} ORDER BY node_id LIMIT ?",
                      [*params, limit])
    return [json.loads(row["data"]) for row in rows]


def children(db, node_id: str) -> list[dict]:
    return nodes(db, parent_id=node_id)


def descendants(db, node_id: str) -> list[str]:
    """The node and every node below it; a cycle would be a corrupt store, so it is refused."""
    seen, frontier = [node_id], [node_id]
    while frontier:
        current = frontier.pop()
        for child in children(db, current):
            require(child["node_id"] not in seen, "tree_cycle")
            seen.append(child["node_id"])
            frontier.append(child["node_id"])
    return seen


def path(db, node_id: str) -> list[dict]:
    """Root-first node chain; a missing parent is a corrupt tree, not an empty path."""
    chain, current, guard = [], node_id, 0
    while current is not None:
        guard += 1
        require(guard <= 256, "tree_cycle")
        item = node(db, current)
        chain.append({"node_id": item["node_id"], "name": item["name"]})
        current = item["parent_id"]
    return list(reversed(chain))


def create_node(db, *, name: str, node_type: str = "organization", parent_id: str = ROOT_NODE,
                entity_anchor: str | None = None, scope_description: str | None = None,
                accepted_relations=(), context_constraints=(), evidence=(),
                status: str | None = None, producer: str = "model",
                recorded_at: str) -> dict:
    """Create one node. An entity node publishes immediately; an organization starts candidate."""
    require(node_type in TREE_NODE_TYPES, "tree_node_type_unknown")
    require(isinstance(name, str) and bool(name.strip()), "tree_node_name_missing")
    parent = node(db, parent_id)
    require(parent["status"] != "retired", "tree_node_retired")
    require(all(kind in ORGANIZATION_RELATIONS for kind in accepted_relations),
            "relation_kind_unknown")
    normalized = " ".join(name.split())
    node_id = "node_" + digest({"parent": parent_id, "name": normalized.casefold()})[:16]
    existing = _row(db, node_id)
    if existing is not None:
        return {**json.loads(existing["data"]), "operation": "CREATE_NODE", "changed": False}
    status = status or ("active" if node_type == "entity" else "candidate")
    require(status in ("candidate", "active"), "tree_node_status_invalid")
    contract = {"node_id": node_id, "node_type": node_type,
                "entity_anchor": None if entity_anchor is None else normalize(entity_anchor,
                                                                             field="entity"),
                "scope_description": scope_description,
                "accepted_relations": list(accepted_relations),
                "context_constraints": list(context_constraints),
                "evidence_refs": list(evidence), "contract_revision": 1}
    data = {"node_id": node_id, "parent_id": parent_id, "node_type": node_type,
            "name": normalized, "status": status, "contract": contract,
            "evidence": list(evidence), "created_at": recorded_at, "producer": producer}
    db.execute("INSERT INTO tree_nodes(node_id, parent_id, node_type, name, status, contract, "
               "evidence, created_at, data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (node_id, parent_id, node_type, normalized, status,
                json.dumps(contract, sort_keys=True), json.dumps(list(evidence)), recorded_at,
                json.dumps(data, sort_keys=True, ensure_ascii=False)))
    operation = "CREATE_ENTITY" if node_type == "entity" else "CREATE_NODE"
    published = _publish(db, operation, target_refs=[node_id], source_refs=[],
                         payload={"parent_id": parent_id, "status": status},
                         recorded_at=recorded_at)
    return {**data, "operation": operation, "changed": True,
            "tree_revision": published["tree_revision"]}


def scope_check(db, target: dict, identity: dict, *, relation: str | None = None) -> dict:
    """The contract decides whether a memory may live in this node; refusal is a code."""
    contract = target["contract"]
    anchor = contract.get("entity_anchor")
    if anchor is not None and normalize(anchor) != normalize(identity["entity"]):
        return {"ok": False, "code": "tree_scope_entity_mismatch"}
    accepted = contract.get("accepted_relations") or []
    if accepted:
        if relation is None:
            return {"ok": False, "code": "tree_scope_relation_missing"}
        if relation not in accepted:
            return {"ok": False, "code": "tree_scope_relation_not_accepted"}
    elif relation is not None:
        require(relation in ORGANIZATION_RELATIONS, "relation_kind_unknown")
    constraints = contract.get("context_constraints") or []
    if constraints and not set(identity["contexts"]) <= set(constraints):
        return {"ok": False, "code": "tree_scope_context_mismatch"}
    if not identity.get("identity_evidence"):
        return {"ok": False, "code": "tree_scope_evidence_missing"}
    return {"ok": True, "code": "tree_scope_match"}


def mount(db, memory_id: str, node_id: str, *, relation: str | None = None, evidence=(),
          producer: str = "model", recorded_at: str, allow_candidate: bool = False) -> dict:
    """Attach a memory to a node. Structure changes; the memory's revision does not."""
    target = node(db, node_id)
    require(target["status"] == "active" or allow_candidate, "tree_node_inactive")
    identity = identities.identity_row(db, memory_id)
    require(not identity.get("merged_into"), "memory_identity_merged")
    check = scope_check(db, target, identity, relation=relation)
    require(check["ok"], check["code"])
    cursor = db.execute("INSERT OR IGNORE INTO tree_mounts(node_id, memory_id, relation, "
                        "created_at) VALUES(?, ?, ?, ?)",
                        (node_id, memory_id, relation, recorded_at))
    if not cursor.rowcount:
        return {"operation": "MOUNT", "memory_id": memory_id, "node_id": node_id,
                "changed": False, "paths": paths_of(db, memory_id)}
    published = _publish(db, "MOUNT", target_refs=[node_id], source_refs=[memory_id],
                         payload={"relation": relation}, recorded_at=recorded_at)
    return {"operation": "MOUNT", "memory_id": memory_id, "node_id": node_id,
            "changed": True, "tree_revision": published["tree_revision"],
            "paths": paths_of(db, memory_id)}


def mount_or_defer(db, namespace: str, memory_id: str, *, node_id: str | None = None,
                   candidates=(), evidence=(), reason: str = "tree_node_ambiguous",
                   missing=("node",), producer: str = "model", recorded_at: str) -> dict:
    """Mount when the node is known; park the attribution when it is not."""
    if node_id is not None:
        return mount(db, memory_id, node_id, evidence=evidence, producer=producer,
                     recorded_at=recorded_at)
    record = pendings.open_mount(db, namespace, memory_id, candidates=candidates,
                                 reason=reason, missing=missing, source_ids=evidence,
                                 producer=producer, recorded_at=recorded_at)
    return {"operation": "DEFER", "pending_id": record["pending_id"], "memory_id": memory_id,
            "changed": record["changed"], "reason": record["reason"],
            "candidate_targets": record["candidate_targets"],
            "missing_conditions": record["missing_conditions"]}


def coverage(db, node_id: str) -> list[str]:
    """Distinct live memories mounted in the subtree: the promotion threshold's unit."""
    scope = descendants(db, node_id)
    marks = ",".join("?" * len(scope))
    rows = db.execute(f"SELECT DISTINCT memory_id FROM tree_mounts WHERE node_id IN ({marks}) "
                      "ORDER BY memory_id", scope)
    live = []
    for row in rows:
        identity = identities.identity_row(db, row["memory_id"])
        if not identity.get("merged_into"):
            live.append(row["memory_id"])
    return live


def _window_ok(db, recorded_at: str, window_seconds: float | None) -> bool:
    """Structural churn is rate-limited: a tree that moves every turn cannot be trusted."""
    window = window_seconds if window_seconds is not None else getmeta(db, "tree_stability_window")
    last = getmeta(db, "tree_last_structural_at")
    if not window or not last:
        return True
    elapsed = (parse_instant(recorded_at) - parse_instant(last)).total_seconds()
    return elapsed >= float(window)


def _mark_structural(db, recorded_at: str) -> None:
    setmeta(db, "tree_last_structural_at", recorded_at)


def promote(db, node_id: str, *, evidence=(), threshold: int = 2, window_seconds: float | None = None,
            producer: str = "model", recorded_at: str) -> dict:
    """Publish a candidate organization node once coverage, contract and evidence agree."""
    target = node(db, node_id)
    require(target["node_type"] == "organization", "tree_promote_entity")
    require(target["status"] == "candidate", "tree_promote_not_candidate")
    contract = target["contract"]
    require(bool(contract.get("scope_description")), "tree_scope_description_missing")
    require(bool(contract.get("evidence_refs") or evidence), "tree_scope_evidence_missing")
    covered = coverage(db, node_id)
    require(len(covered) >= threshold, "tree_promote_coverage_low")
    require(_window_ok(db, recorded_at, window_seconds), "tree_stability_window")
    contract["contract_revision"] += 1
    contract["evidence_refs"] = list(dict.fromkeys([*contract.get("evidence_refs", []),
                                                    *evidence]))
    target.update({"status": "active", "contract": contract, "promoted_at": recorded_at})
    db.execute("UPDATE tree_nodes SET status = ?, contract = ?, data = ? WHERE node_id = ?",
               ("active", json.dumps(contract, sort_keys=True),
                json.dumps(target, sort_keys=True, ensure_ascii=False), node_id))
    published = _publish(db, "PROMOTE", target_refs=[node_id], source_refs=covered,
                         payload={"coverage": covered, "threshold": threshold,
                                  "contract_revision": contract["contract_revision"]},
                         recorded_at=recorded_at)
    _mark_structural(db, recorded_at)
    return {"operation": "PROMOTE", "node_id": node_id, "status": "active",
            "coverage": covered, "tree_revision": published["tree_revision"],
            "contract_revision": contract["contract_revision"], "changed": True}


def update_contract(db, node_id: str, *, scope_description: str | None = None,
                    accepted_relations=None, context_constraints=None, evidence=(),
                    producer: str = "model", recorded_at: str) -> dict:
    """Change what a node accepts. Contract revision moves; memory revisions never do."""
    target = node(db, node_id)
    contract = target["contract"]
    if scope_description is not None:
        contract["scope_description"] = scope_description
    if accepted_relations is not None:
        require(all(kind in ORGANIZATION_RELATIONS for kind in accepted_relations),
                "relation_kind_unknown")
        contract["accepted_relations"] = list(accepted_relations)
    if context_constraints is not None:
        contract["context_constraints"] = list(context_constraints)
    contract["evidence_refs"] = list(dict.fromkeys([*contract.get("evidence_refs", []),
                                                    *evidence]))
    contract["contract_revision"] += 1
    target["contract"] = contract
    db.execute("UPDATE tree_nodes SET contract = ?, data = ? WHERE node_id = ?",
               (json.dumps(contract, sort_keys=True),
                json.dumps(target, sort_keys=True, ensure_ascii=False), node_id))
    published = _publish(db, "CONTRACT", target_refs=[node_id], source_refs=[],
                         payload={"contract_revision": contract["contract_revision"]},
                         recorded_at=recorded_at)
    return {"operation": "CONTRACT", "node_id": node_id, "contract": contract,
            "tree_revision": published["tree_revision"], "changed": True}


def retire(db, node_id: str, *, evidence=(), producer: str = "model", recorded_at: str) -> dict:
    """Retire an empty node. A node that still holds memories must be merged first."""
    target = node(db, node_id)
    require(node_id != ROOT_NODE, "tree_root_retire")
    require(target["status"] != "retired", "tree_node_retired")
    require(not coverage(db, node_id), "tree_node_not_empty")
    target.update({"status": "retired", "retired_at": recorded_at})
    db.execute("UPDATE tree_nodes SET status = 'retired', data = ? WHERE node_id = ?",
               (json.dumps(target, sort_keys=True, ensure_ascii=False), node_id))
    published = _publish(db, "RETIRE", target_refs=[node_id], source_refs=list(evidence),
                         payload={}, recorded_at=recorded_at)
    return {"operation": "RETIRE", "node_id": node_id, "tree_revision": published["tree_revision"],
            "changed": True}


def merge_nodes(db, source: str, target: str, *, evidence=(), producer: str = "model",
                recorded_at: str) -> dict:
    """Fold one node into another: mounts move, the source retires, facts stay untouched."""
    source_node = node(db, source)
    target_node = node(db, target)
    require(source != target, "tree_merge_self")
    require(source != ROOT_NODE, "tree_root_merge")
    require(target_node["status"] == "active", "tree_node_inactive")
    require(source_node["node_type"] == target_node["node_type"], "tree_merge_type_mismatch")
    rows = db.execute("SELECT memory_id FROM tree_mounts WHERE node_id = ?", (source,)).fetchall()
    moved = []
    for row in rows:
        cursor = db.execute("INSERT OR IGNORE INTO tree_mounts(node_id, memory_id, relation, "
                            "created_at) VALUES(?, ?, NULL, ?)",
                            (target, row["memory_id"], recorded_at))
        if cursor.rowcount:
            moved.append(row["memory_id"])
        db.execute("DELETE FROM tree_mounts WHERE node_id = ? AND memory_id = ?",
                   (source, row["memory_id"]))
    source_node.update({"status": "retired", "merged_into": target, "retired_at": recorded_at})
    db.execute("UPDATE tree_nodes SET status = 'retired', data = ? WHERE node_id = ?",
               (json.dumps(source_node, sort_keys=True, ensure_ascii=False), source))
    published = _publish(db, "MERGE", target_refs=[target], source_refs=[source, *moved],
                         payload={"moved": moved}, recorded_at=recorded_at)
    _mark_structural(db, recorded_at)
    return {"operation": "MERGE", "source": source, "target": target, "moved": moved,
            "tree_revision": published["tree_revision"], "changed": True}


def propose_merge(db, source: str, target: str, *, reason: str = "tree_merge_proposed",
                  producer: str = "model", recorded_at: str) -> dict:
    """Record the proposal; nothing moves until the caller publishes the operation."""
    node(db, source)
    node(db, target)
    previous = _head(db)
    published = _publish(db, "MERGE", target_refs=[target], source_refs=[source],
                         payload={"reason": reason, "applied": False}, recorded_at=recorded_at,
                         status="proposed", previous=previous)
    return {**published, "changed": True, "reason": reason}


def split_node(db, source: str, assignments: dict, *, evidence=(), producer: str = "model",
               recorded_at: str) -> dict:
    """Move named mounts from one node into already-created children."""
    node(db, source)
    require(bool(assignments), "tree_split_empty")
    moved = []
    for child_id, memory_ids in assignments.items():
        child = node(db, child_id)
        require(child["parent_id"] == source, "tree_split_child_not_under_source")
        for memory_id in memory_ids:
            cursor = db.execute("INSERT OR IGNORE INTO tree_mounts(node_id, memory_id, relation, "
                                "created_at) VALUES(?, ?, NULL, ?)",
                                (child_id, memory_id, recorded_at))
            if cursor.rowcount:
                moved.append({"node_id": child_id, "memory_id": memory_id})
            db.execute("DELETE FROM tree_mounts WHERE node_id = ? AND memory_id = ?",
                       (source, memory_id))
    published = _publish(db, "SPLIT", target_refs=list(assignments), source_refs=[source],
                         payload={"moved": moved}, recorded_at=recorded_at)
    _mark_structural(db, recorded_at)
    return {"operation": "SPLIT", "source": source, "moved": moved,
            "tree_revision": published["tree_revision"], "changed": True}


def publish_op(db, op_id: int, *, recorded_at: str) -> dict:
    """Publish a proposed operation, refusing if the tree moved underneath it."""
    row = db.execute("SELECT * FROM tree_ops WHERE op_id = ?", (op_id,)).fetchone()
    require(row is not None, "tree_operation_unknown")
    require(row["status"] == "proposed", "tree_operation_not_proposed")
    require(row["previous_revision"] == _head(db), "tree_operation_stale")
    db.execute("UPDATE tree_ops SET status = 'published', tree_revision = ? WHERE op_id = ?",
               (_head(db) + 1, op_id))
    setmeta(db, "tree_head", _head(db) + 1)
    return {"op_id": op_id, "operation_type": row["operation_type"], "status": "published",
            "tree_revision": _head(db), "changed": True}


def ops(db, *, limit: int = 100, status: str | None = None) -> list[dict]:
    if status is None:
        rows = db.execute("SELECT * FROM tree_ops ORDER BY op_id DESC LIMIT ?", (limit,))
    else:
        rows = db.execute("SELECT * FROM tree_ops WHERE status = ? ORDER BY op_id DESC LIMIT ?",
                          (status, limit))
    return [{"op_id": row["op_id"], "tree_revision": row["tree_revision"],
             "operation_type": row["operation_type"], "status": row["status"],
             "target_refs": json.loads(row["target_refs"]),
             "source_refs": json.loads(row["source_refs"]),
             "previous_revision": row["previous_revision"],
             "payload": json.loads(row["payload"]), "recorded_at": row["recorded_at"]}
            for row in rows]


def paths_of(db, memory_id: str) -> list[dict]:
    """Every path a memory is reachable by; multi-mount is a feature, not a duplicate."""
    rows = db.execute("SELECT node_id, relation FROM tree_mounts WHERE memory_id = ? "
                      "ORDER BY node_id", (memory_id,)).fetchall()
    return [{"node_id": row["node_id"], "relation": row["relation"],
             "path": [item["name"] for item in path(db, row["node_id"])]} for row in rows]


def mounts(db, node_id: str) -> list[dict]:
    return [{"memory_id": row["memory_id"], "relation": row["relation"],
             "created_at": row["created_at"]}
            for row in db.execute("SELECT * FROM tree_mounts WHERE node_id = ? "
                                  "ORDER BY memory_id", (node_id,))]


def scope_intersection(db, left: dict, right: dict) -> dict:
    """§11.3: measure the three overlaps between two nodes; overlap is never equivalence.

    Semantic candidates, typed relations and actual Memory ID coverage are reported
    separately. Coverage Jaccard is a measurement of index overlap, not a merge licence:
    two nodes can cover the same memories and still mean different things.
    """
    left_contract, right_contract = left["contract"], right["contract"]
    left_anchor = left_contract.get("entity_anchor")
    right_anchor = right_contract.get("entity_anchor")
    entity = {"anchors": [left_anchor, right_anchor],
              "compatible": left_anchor is None or right_anchor is None
              or normalize(left_anchor) == normalize(right_anchor)}
    left_relations = set(left_contract.get("accepted_relations") or [])
    right_relations = set(right_contract.get("accepted_relations") or [])
    relations = {"shared": sorted(left_relations & right_relations),
                 "compatible": not left_relations or not right_relations
                 or bool(left_relations & right_relations)}
    left_contexts = set(left_contract.get("context_constraints") or [])
    right_contexts = set(right_contract.get("context_constraints") or [])
    contexts = {"shared": sorted(left_contexts & right_contexts),
                "compatible": not left_contexts or not right_contexts
                or bool(left_contexts & right_contexts)}
    left_cover = set(coverage(db, left["node_id"]))
    right_cover = set(coverage(db, right["node_id"]))
    shared = left_cover & right_cover
    union = left_cover | right_cover
    coverage_axis = {"left": len(left_cover), "right": len(right_cover), "shared": len(shared),
                     "jaccard": round(len(shared) / len(union), 4) if union else 0.0}
    return {"left": left["node_id"], "right": right["node_id"],
            "intersects": entity["compatible"] and relations["compatible"]
            and contexts["compatible"],
            "axes": {"entity": entity, "relations": relations, "contexts": contexts,
                     "coverage": coverage_axis},
            "semantic_equivalence": False,
            "note": "coverage_overlap_is_not_semantic_equivalence"}


def tree(db) -> dict:
    """Whole-structure read for the CLI and for rebuild verification."""
    all_nodes = nodes(db, limit=10000)
    return {"root": ROOT_NODE, "revision": _head(db), "node_count": len(all_nodes),
            "nodes": all_nodes,
            "mounts": [{"node_id": row["node_id"], "memory_id": row["memory_id"],
                        "relation": row["relation"]}
                       for row in db.execute("SELECT * FROM tree_mounts "
                                             "ORDER BY node_id, memory_id")],
            "recent_ops": ops(db, limit=20)}
