"""Typed semantic relation graph (§9).

One storage, two families, two execution semantics:

* organization relations (IS_A / PART_OF / OWNED_BY / PRODUCES / ABOUT) organize retrieval;
* dependency relations (CONSTRAINT / CAUSAL / ASSOCIATION) describe effect and are read by
  the dependency resolver, which proposes impact but never commits state.

A relation is a candidate until it carries evidence. Traversal ignores candidates by default,
so a model-proposed edge cannot silently widen what retrieval treats as confirmed.
"""
from __future__ import annotations

import json

from ..contracts import digest
from .contracts import require
from .contracts import (CSMError, DEPENDENCY_RELATIONS, ORGANIZATION_RELATIONS,
                        RELATION_KINDS, TRUTHS, anchors)

REF_KINDS = ("memory", "node", "action")


def memory_ref(memory_id: str) -> str:
    return f"memory:{memory_id}"


def node_ref(node_id: str) -> str:
    return f"node:{node_id}"


def action_ref(name: str) -> str:
    return f"action:{name}"


def split_ref(ref: str) -> tuple[str, str]:
    kind, _, value = ref.partition(":")
    require(kind in REF_KINDS and bool(value), "relation_ref_invalid")
    return kind, value


def _exists(db, ref: str) -> None:
    kind, value = split_ref(ref)
    if kind == "action":
        return  # an action is a name declared by the edge, not a stored object
    table = "identities" if kind == "memory" else "tree_nodes"
    column = "memory_id" if kind == "memory" else "node_id"
    row = db.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)).fetchone()
    require(row is not None, "relation_ref_unknown")


def _evidence(db, evidence) -> list[str]:
    ids = [item for item in dict.fromkeys(evidence or ()) if item]
    require(bool(ids), "relation_evidence_missing")
    marks = ",".join("?" * len(ids))
    found = {row["id"] for row in
             db.execute(f"SELECT id FROM events WHERE id IN ({marks})", ids)}
    require(all(item in found for item in ids), "evidence_source_unknown")
    return ids


def relation_id(kind: str, subject: str, object: str, contexts) -> str:
    return "rel_" + digest({"kind": kind, "subject": subject, "object": object,
                            "contexts": list(contexts)})[:24]


def _row(db, rel_id: str) -> dict | None:
    row = db.execute("SELECT data FROM relations WHERE rel_id = ?", (rel_id,)).fetchone()
    return None if row is None else json.loads(row["data"])


def link(db, *, kind: str, subject: str, object: str, contexts=(),
         evidence, producer: str = "model", recorded_at: str, confirmed: bool = False) -> dict:
    """Add one typed edge. The same (kind, subject, object, contexts) is idempotent."""
    require(kind in RELATION_KINDS, "relation_kind_unknown")
    require(subject != object, "relation_self")
    split_ref(subject)
    split_ref(object)
    _exists(db, subject)
    _exists(db, object)
    source_ids = _evidence(db, evidence)
    context_list = list(anchors(contexts, field="context"))
    rel_id = relation_id(kind, subject, object, context_list)
    existing = _row(db, rel_id)
    if existing is not None:
        return {**existing, "changed": False}
    data = {"rel_id": rel_id, "kind": kind, "subject": subject, "object": object,
            "contexts": context_list, "confirmed": bool(confirmed),
            "truth": "UNKNOWN" if kind in DEPENDENCY_RELATIONS else None,
            "evidence": source_ids, "producer": producer, "recorded_at": recorded_at,
            "confirmations": []}
    db.execute("INSERT INTO relations(rel_id, kind, subject, object, contexts, confirmed, truth, "
               "evidence, producer, recorded_at, data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (rel_id, kind, subject, object, json.dumps(context_list), int(bool(confirmed)),
                data["truth"], json.dumps(source_ids), producer, recorded_at,
                json.dumps(data, sort_keys=True, ensure_ascii=False)))
    return {**data, "changed": True}


def confirm(db, rel_id: str, *, evidence, producer: str = "model",
            recorded_at: str) -> dict:
    """Promote a candidate edge to traversable; evidence is mandatory."""
    data = _row(db, rel_id)
    require(data is not None, "relation_unknown")
    if data["confirmed"]:
        return {**data, "changed": False}
    source_ids = _evidence(db, evidence)
    data["confirmed"] = True
    data["confirmations"].append({"evidence": source_ids, "producer": producer,
                                  "recorded_at": recorded_at})
    db.execute("UPDATE relations SET confirmed = 1, data = ? WHERE rel_id = ?",
               (json.dumps(data, sort_keys=True, ensure_ascii=False), rel_id))
    return {**data, "changed": True}


def set_truth(db, rel_id: str, truth: str, *, evidence=(), producer: str = "model",
              recorded_at: str) -> dict:
    """Record a three-valued premise truth. TRUE/FALSE need evidence; UNKNOWN needs none."""
    data = _row(db, rel_id)
    require(data is not None, "relation_unknown")
    require(data["kind"] in DEPENDENCY_RELATIONS, "relation_truth_not_dependency")
    require(truth in TRUTHS, "relation_truth_invalid")
    if truth == data["truth"]:
        return {**data, "changed": False}
    source_ids = _evidence(db, evidence) if truth != "UNKNOWN" else list(evidence or ())
    data["truth"] = truth
    data["truth_history"] = data.get("truth_history", []) + [
        {"truth": truth, "evidence": source_ids, "producer": producer,
         "recorded_at": recorded_at}]
    db.execute("UPDATE relations SET truth = ?, data = ? WHERE rel_id = ?",
               (truth, json.dumps(data, sort_keys=True, ensure_ascii=False), rel_id))
    return {**data, "changed": True}


def of_ref(db, ref: str, *, kinds=(), direction: str = "out", confirmed_only: bool = True,
           limit: int = 100) -> list[dict]:
    """Edges attached to one reference. ``direction`` is out / in / both."""
    require(direction in ("out", "in", "both"), "relation_direction_invalid")
    split_ref(ref)
    clauses, params = [], []
    if confirmed_only:
        clauses.append("confirmed = 1")
    if kinds:
        require(all(kind in RELATION_KINDS for kind in kinds), "relation_kind_unknown")
        clauses.append(f"kind IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    side = []
    if direction in ("out", "both"):
        side.append("subject = ?")
        params.append(ref)
    if direction in ("in", "both"):
        side.append("object = ?")
        params.append(ref)
    clauses.append("(" + " OR ".join(side) + ")")
    rows = db.execute(f"SELECT data FROM relations WHERE {' AND '.join(clauses)} "
                      "ORDER BY rel_id LIMIT ?", [*params, limit])
    return [json.loads(row["data"]) for row in rows]


def of_memory(db, memory_id: str, *, kinds=(), direction: str = "out",
              confirmed_only: bool = True) -> list[dict]:
    return of_ref(db, memory_ref(memory_id), kinds=kinds, direction=direction,
                  confirmed_only=confirmed_only)


def neighbors(db, ref: str, *, kinds=(), direction: str = "out",
              confirmed_only: bool = True, limit: int = 100) -> list[dict]:
    """The reachable references, each tagged with the edge that reached it."""
    out = []
    for edge in of_ref(db, ref, kinds=kinds, direction=direction,
                       confirmed_only=confirmed_only, limit=limit):
        if edge["subject"] == ref:
            out.append({"ref": edge["object"], "kind": edge["kind"], "rel_id": edge["rel_id"],
                        "direction": "out"})
        if edge["object"] == ref and direction in ("in", "both"):
            out.append({"ref": edge["subject"], "kind": edge["kind"], "rel_id": edge["rel_id"],
                        "direction": "in"})
    return out


def expand(db, origins, *, depth: int = 1, kinds=(), confirmed_only: bool = True,
           limit: int = 50) -> dict:
    """Breadth-first traversal, bounded by depth and a hard result cap."""
    require(isinstance(depth, int) and not isinstance(depth, bool) and 1 <= depth <= 2,
            "relation_depth_invalid")
    frontier = list(dict.fromkeys(origins))
    visited = list(frontier)
    edges = []
    level = 0
    while frontier and level < depth and len(edges) < limit:
        nxt = []
        for ref in frontier:
            for step in neighbors(db, ref, kinds=kinds, confirmed_only=confirmed_only):
                edges.append({**step, "from": ref, "depth": level + 1})
                if step["ref"] not in visited:
                    visited.append(step["ref"])
                    nxt.append(step["ref"])
                if len(edges) >= limit:
                    break
            if len(edges) >= limit:
                break
        frontier = nxt
        level += 1
    return {"origins": list(origins), "depth": depth, "visited": visited, "edges": edges,
            "truncated": len(edges) >= limit}


def graph_of(db, memory_id: str, *, direction: str = "both") -> dict:
    """Both families for one memory, split so the caller cannot confuse them."""
    return {"memory_id": memory_id,
            "organization": of_memory(db, memory_id, kinds=ORGANIZATION_RELATIONS,
                                      direction=direction),
            "dependency": of_memory(db, memory_id, kinds=DEPENDENCY_RELATIONS,
                                    direction=direction)}
