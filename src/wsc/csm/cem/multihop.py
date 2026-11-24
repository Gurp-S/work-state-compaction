"""Multi-hop retrieval: follow the evidence graph, and say which edge reached each memory.

A single query answers only what one memory says. Questions that need a second memory — the
manager of the person who owns the account — require the first hop's hits to become the
second hop's anchors. Every added result keeps the edge that produced it, so the caller can
tell a direct match from a reachable neighbour instead of trusting a flat list.
"""
from __future__ import annotations

from . import filters
from .. import identity as identities
from . import relations
from .. import retrieval
from .. import state
from ..contracts import CSMError, RELATION_KINDS
from .candidate_budget import select_candidates
from .result_scope import loss_scope


def _view(db, memory_id: str) -> dict | None:
    try:
        owner = identities.live(db, memory_id)
    except CSMError:
        return None
    record = state.head(db, owner["memory_id"])
    if record is None:
        return None
    return retrieval._view(db, owner, record)


def _neighbours(db, results: list[dict], *, kinds, seen: set) -> list[dict]:
    seeds = [relations.memory_ref(item["memory_id"]) for item in results
             if item.get("classification") == "CURRENT_CONFIRMED" and item.get("memory_id")]
    if not seeds:
        return []
    walked = relations.expand(db, seeds, depth=1, kinds=kinds, confirmed_only=True)
    additions = []
    for edge in walked["edges"]:
        kind, ref_id = relations.split_ref(edge["ref"])
        if kind != "memory" or ref_id in seen:
            continue
        item = _view(db, ref_id)
        if item is None:
            continue
        origin_kind, origin_id = relations.split_ref(edge["from"])
        item.update({"classification": "UNKNOWN", "confirmed": False,
                     "reason": "multihop_neighbour",
                     "via": {"hop": edge["depth"], "from": origin_id if origin_kind == "memory"
                             else origin_id, "kind": edge["kind"], "rel_id": edge["rel_id"]},
                     "uncertainty": {"classification": "UNKNOWN", "confirmed": False,
                                     "missing_conditions": ["direct_observation"]}})
        seen.add(ref_id)
        additions.append(item)
    return additions


def explore(db, text: str, limit: int = 20, *, hops: int = 2, kinds=RELATION_KINDS,
            diverse: bool = False, entities=None, contexts=None, lifecycle=None,
            status=None, window=None) -> dict:
    """Hop 1 is the ordinary search; later hops expand relations and, once, the query text."""
    hops = max(1, min(int(hops or 1), 3))
    anchors = {"entities": entities, "contexts": contexts, "lifecycle": lifecycle,
               "status": status, "window": window}
    base = retrieval.search(db, text, limit=limit, **anchors)
    results = list(base.get("results", []))
    seen = {item.get("memory_id") for item in results if item.get("memory_id")}
    trace = [{"hop": 1, "via": "search", "added": len(results)}]
    for hop in range(2, hops + 1):
        additions = _neighbours(db, results, kinds=kinds, seen=seen)
        if hop == 2 and results:
            # One expansion of the query by what hop 1 found: still mechanical, still cited.
            expanded = " ".join(str(item.get("value") or "") for item in results[:3]).strip()
            if expanded:
                second = retrieval.search(db, expanded[:400], limit=max(1, limit // 2),
                                          **anchors)
                for item in second.get("results", []):
                    memory_id = item.get("memory_id")
                    if memory_id in seen:
                        continue
                    seen.add(memory_id)
                    item = {**item, "reason": "multihop_expansion",
                            "via": {"hop": 2, "from": "query_expansion", "kind": "text"}}
                    additions.append(item)
        trace.append({"hop": hop, "via": "relations+expansion", "added": len(additions)})
        results.extend(additions)
        if not additions:
            break
    if filters.enabled("filters"):
        results = [item for item in results if filters.keep(item, **anchors)[0]]
    selected, counts = select_candidates(results, limit, diverse=diverse)
    omitted = len({item.get("memory_id") for item in results}) - len(selected)
    return {"query": {"text": text}, "results": selected, "hops": hops,
            "trace": trace, "counts": counts, **loss_scope(base, omitted)}


__all__ = ["RELATION_KINDS", "explore"]
