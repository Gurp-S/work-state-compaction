"""Shadow Tree (§12.7): rehearse a structural change on a candidate tree before publishing it.

The candidate tree is a pure in-memory copy of ``tree_nodes``/``tree_mounts``; nothing is
written until ``apply`` runs the real operations inside one transaction. ``evaluate`` answers the
questions the design asks of a shadow run: can every mounted memory still be recalled, did the
candidate set shrink, what does retrieval cost, and are structural invariants violated.

Operation dicts (same vocabulary as the tree module):

    {"op": "create_node", "name": "...", "parent_id": "root", "node_type": "organization"}
    {"op": "mount", "memory_id": "...", "node_id": "...", "relation": null}
    {"op": "promote", "node_id": "..."}
    {"op": "merge", "source": "...", "target": "..."}
    {"op": "retire", "node_id": "..."}
"""
from __future__ import annotations

import json

from ..contracts import digest
from .contracts import CSMError, require
from .store import ROOT_NODE


def _snapshot(db) -> tuple[dict, list[dict]]:
    nodes = {row["node_id"]: json.loads(row["data"])
             for row in db.execute("SELECT node_id, data FROM tree_nodes")}
    mounts = [dict(row) for row in db.execute(
        "SELECT node_id, memory_id, relation FROM tree_mounts")]
    return nodes, mounts


def _simulate(nodes: dict, mounts: list[dict], operations: list[dict]):
    nodes = {node_id: json.loads(json.dumps(data)) for node_id, data in nodes.items()}
    mounts = [dict(item) for item in mounts]
    created: list[str] = []
    for operation in operations:
        kind = operation.get("op")
        if kind == "create_node":
            name = " ".join(str(operation.get("name") or "").split())
            require(bool(name), "tree_node_name_missing")
            parent_id = operation.get("parent_id") or ROOT_NODE
            node_id = "node_" + digest({"parent": parent_id,
                                        "name": name.casefold()})[:16]
            if node_id not in nodes:
                nodes[node_id] = {"node_id": node_id, "parent_id": parent_id,
                                  "node_type": operation.get("node_type", "organization"),
                                  "name": name, "status": operation.get("status", "candidate"),
                                  "contract": {"node_id": node_id,
                                               "entity_anchor": operation.get("entity_anchor"),
                                               "scope_description": None,
                                               "accepted_relations": [], "context_constraints": []}}
                created.append(node_id)
        elif kind == "mount":
            mounts.append({"node_id": operation["node_id"],
                           "memory_id": operation["memory_id"],
                           "relation": operation.get("relation")})
        elif kind == "promote":
            if operation["node_id"] in nodes:
                nodes[operation["node_id"]]["status"] = "active"
        elif kind == "retire":
            if operation["node_id"] in nodes:
                nodes[operation["node_id"]]["status"] = "retired"
        elif kind == "merge":
            source, target = operation["source"], operation["target"]
            for item in mounts:
                if item["node_id"] == source:
                    item["node_id"] = target
            for data in nodes.values():
                if data.get("parent_id") == source:
                    data["parent_id"] = target
            nodes.pop(source, None)
        else:
            raise CSMError("shadow_operation_unknown")
    return nodes, mounts, created


def _depth(nodes: dict, node_id: str, limit: int = 64) -> int:
    depth = 0
    while node_id not in (None, ROOT_NODE) and depth < limit:
        node = nodes.get(node_id)
        if node is None:
            return -1
        node_id = node.get("parent_id")
        depth += 1
    return depth if node_id == ROOT_NODE else -1


def _metrics(db, nodes: dict, mounts: list[dict]) -> dict:
    identities = {row["memory_id"]: json.loads(row["data"])
                  for row in db.execute("SELECT memory_id, data FROM identities")}
    children: dict[str, int] = {}
    for node in nodes.values():
        children[node.get("parent_id")] = children.get(node.get("parent_id"), 0) + 1
    broken = []
    for item in mounts:
        depth = _depth(nodes, item["node_id"])
        node = nodes.get(item["node_id"])
        if node is None or node.get("status") == "retired" or depth < 0:
            broken.append(item["memory_id"])
    mis_mounts = []
    for item in mounts:
        node = nodes.get(item["node_id"])
        identity = identities.get(item["memory_id"])
        if node is None or identity is None:
            continue
        anchor = (node.get("contract") or {}).get("entity_anchor")
        if anchor and anchor != identity["entity"]:
            mis_mounts.append(item["memory_id"])
    depths = [_depth(nodes, item["node_id"]) for item in mounts]
    return {
        "nodes": len(nodes),
        "active_nodes": sum(1 for node in nodes.values() if node.get("status") == "active"),
        "candidate_nodes": sum(1 for node in nodes.values() if node.get("status") == "candidate"),
        "mounts": len(mounts),
        "max_depth": max(depths) if depths else 0,
        "max_children": max(children.values()) if children else 0,
        "retrieval_cost": sum(depth + 1 for depth in depths if depth >= 0),
        "unrecallable_memories": sorted(set(broken)),
        "mis_mounted_memories": sorted(set(mis_mounts)),
    }


def _cycles(nodes: dict) -> list[str]:
    seen, cyclic = set(), []
    for node_id in nodes:
        chain, current = set(), node_id
        while current and current != ROOT_NODE:
            if current in chain:
                cyclic.append(node_id)
                break
            chain.add(current)
            current = (nodes.get(current) or {}).get("parent_id")
    return sorted(set(cyclic))


def evaluate(db, operations: list[dict]) -> dict:
    """Rehearse ``operations`` and return a report; ``ok`` means invariants hold."""
    baseline_nodes, baseline_mounts = _snapshot(db)
    nodes, mounts, created = _simulate(baseline_nodes, baseline_mounts, operations)
    baseline = _metrics(db, baseline_nodes, baseline_mounts)
    candidate = _metrics(db, nodes, mounts)
    violations = []
    if candidate["unrecallable_memories"]:
        violations.append({"code": "tree_mount_unreachable",
                           "memory_ids": candidate["unrecallable_memories"][:20]})
    if candidate["mis_mounted_memories"]:
        violations.append({"code": "tree_scope_entity_mismatch",
                           "memory_ids": candidate["mis_mounted_memories"][:20]})
    cyclic = _cycles(nodes)
    if cyclic:
        violations.append({"code": "tree_cycle", "node_ids": cyclic[:20]})
    missing_parent = [node["node_id"] for node in nodes.values()
                      if node["node_id"] != ROOT_NODE
                      and node.get("parent_id") not in nodes and node.get("parent_id") != ROOT_NODE]
    if missing_parent:
        violations.append({"code": "tree_parent_missing", "node_ids": missing_parent[:20]})
    return {
        "ok": not violations,
        "violations": violations,
        "operations": len(operations),
        "created_nodes": created,
        "baseline": baseline,
        "candidate": candidate,
        "improvement": {
            "candidate_nodes": candidate["candidate_nodes"] - baseline["candidate_nodes"],
            "nodes": candidate["nodes"] - baseline["nodes"],
            "retrieval_cost": candidate["retrieval_cost"] - baseline["retrieval_cost"],
        },
    }


def apply(db, operations: list[dict], *, recorded_at: str, producer: str = "model") -> dict:
    """Evaluate first, then publish the operations through the real tree API."""
    from . import tree

    report = evaluate(db, operations)
    if not report["ok"]:
        raise CSMError("shadow_invariant_violation")
    results = []
    for operation in operations:
        kind = operation.get("op")
        if kind == "create_node":
            results.append(tree.create_node(
                db, name=operation["name"],
                node_type=operation.get("node_type", "organization"),
                parent_id=operation.get("parent_id") or ROOT_NODE,
                entity_anchor=operation.get("entity_anchor"),
                status=operation.get("status"), producer=producer, recorded_at=recorded_at))
        elif kind == "mount":
            results.append(tree.mount(
                db, operation["memory_id"], operation["node_id"],
                relation=operation.get("relation"), producer=producer, recorded_at=recorded_at))
        elif kind == "promote":
            results.append(tree.promote(db, operation["node_id"], producer=producer,
                                        recorded_at=recorded_at))
        elif kind == "merge":
            results.append(tree.merge_nodes(db, operation["source"], operation["target"],
                                            producer=producer, recorded_at=recorded_at))
        elif kind == "retire":
            results.append(tree.retire(db, operation["node_id"], producer=producer,
                                       recorded_at=recorded_at))
        else:
            raise CSMError("shadow_operation_unknown")
    return {"report": report, "results": results}
