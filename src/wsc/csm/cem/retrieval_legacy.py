"""Deterministic retrieval over identity anchors, topics, tree scope and pending bindings.

Every result carries its class, so a historical value, an expanded neighbour or an unresolved
binding can never be read as the current confirmed fact (§13.4). Relation expansion is a
deliberate exception: it adds context as UNKNOWN, because reachability is not confirmation.
"""
from __future__ import annotations

import json
import re

from ..contracts import require
from . import domain
from .. import identity as identities
from . import identity_ops
from . import pending as pendings
from . import relations
from .. import state
from . import tree
from .recall_policy import mode as recall_mode
from ..time_selection import as_of
from ..contracts import (CURRENT_CONFIRMED, HISTORICAL, PENDING_BINDING, RELATION_KINDS,
                        UNKNOWN, parse_instant)

CLASS_ORDER = {CURRENT_CONFIRMED: 0, "SPECULATIVE": 1, PENDING_BINDING: 2, UNKNOWN: 3, HISTORICAL: 4}
# At an instant, a value superseded later is the right answer then, while an identity that
# did not exist yet is not. Ranking the present-day labels would do the opposite.
AS_OF_ORDER = {CURRENT_CONFIRMED: 0, HISTORICAL: 1, PENDING_BINDING: 2, UNKNOWN: 3,
               "SPECULATIVE": 4}
TERM_RE = re.compile(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+")


def _terms(text: str) -> list[str]:
    """Words for latin text, characters and bigrams for CJK (no segmenter dependency).

    Bigrams alone miss the common case where a question and a memory share a character but no
    adjacent pair ("住几楼" against "住在四楼"), so single characters are kept as weak terms too.
    """
    out: list[str] = []
    for match in TERM_RE.finditer(text.lower()):
        token = match.group()
        if token.isascii():
            out.append(token)
        else:
            out.extend(token)
            out.extend(token[index:index + 2] for index in range(max(1, len(token) - 1)))
    return out


def _matches(identity: dict, query: dict) -> tuple[bool, str]:
    """True when every anchor the caller supplied is satisfied by this identity."""
    names = query.get("entities") or ()
    if query["entity"] is not None and identity["entity"] != query["entity"] \
            and identity["entity"] not in names:
        return False, "entity_mismatch"
    if query["slot"] is not None and identity["slot"] != query["slot"]:
        return False, "slot_mismatch"
    if query["contexts"] and list(identity["contexts"]) != list(query["contexts"]):
        return False, "context_mismatch"
    return True, "identity_match"


def _candidate_identities(db, query: dict) -> list[dict]:
    seen, out = set(), []

    def add(identity: dict) -> None:
        if identity["memory_id"] not in seen:
            seen.add(identity["memory_id"])
            out.append(identity)

    if query["entity"] is not None or query["slot"] is not None:
        clauses, params = [], []
        names = query.get("entities") or ([query["entity"]]
                                          if query["entity"] is not None else [])
        if names:
            clauses.append(f"entity IN ({','.join('?' * len(names))})")
            params.extend(names)
        if query["slot"] is not None:
            clauses.append("slot = ?")
            params.append(query["slot"])
        for row in db.execute(f"SELECT data FROM identities WHERE {' AND '.join(clauses)} "
                              "ORDER BY memory_id", params):
            add(json.loads(row["data"]))
    if query["topics"]:
        marks = ",".join("?" * len(query["topics"]))
        for row in db.execute("SELECT DISTINCT memory_id FROM memory_topics "
                              f"WHERE topic IN ({marks}) ORDER BY memory_id",
                              list(query["topics"])):
            add(identities.identity_row(db, row["memory_id"]))
    if query["node_id"] is not None:
        tree.node(db, query["node_id"])
        scope = tree.descendants(db, query["node_id"])
        marks = ",".join("?" * len(scope))
        for row in db.execute(f"SELECT DISTINCT memory_id FROM tree_mounts "
                              f"WHERE node_id IN ({marks}) ORDER BY memory_id", scope):
            add(identities.identity_row(db, row["memory_id"]))
    return out


def _pending_matches(db, query: dict) -> list[dict]:
    out = []
    cutoff = parse_instant(query["valid_at"]) if query.get("valid_at") else None
    for item in pendings.listing(db, limit=1000):
        if cutoff is not None:
            # A proposal raised later is not evidence about an earlier instant.
            created = item.get("created_at")
            if not created:
                continue
            try:
                if parse_instant(created) > cutoff:
                    continue
            except (TypeError, ValueError):
                continue
        kind = item.get("pending_type", "identity")
        if kind not in ("identity", "explicit_write"):
            # A structural proposal follows the memory it is about, not the caller's anchors.
            if query["node_id"] is not None:
                continue
            if item.get("memory_id"):
                identity = identities.identity_row(db, item["memory_id"])
                if not _matches(identity, query)[0]:
                    continue
                if query["topics"] and not set(query["topics"]) & set(
                        identities.topics_of(db, item["memory_id"])):
                    continue
            elif (query["entity"] is not None or query["slot"] is not None
                  or query["topics"]):
                continue
            out.append({"classification": PENDING_BINDING, "confirmed": False,
                        "reason": item["reason"], "pending_id": item["pending_id"],
                        "pending_type": kind, "memory_id": item.get("memory_id"),
                        "operation": item.get("operation"),
                        "candidate_targets": item["candidate_targets"],
                        "missing_conditions": item["missing_conditions"],
                        "source_refs": item["source_refs"], "created_at": item["created_at"],
                        "uncertainty": {"classification": PENDING_BINDING, "confirmed": False,
                                        "missing_conditions": item["missing_conditions"]}})
            continue
        if query["entity"] is not None and item["entity"] != query["entity"]:
            continue
        if query["slot"] is not None and item["slot"] != query["slot"]:
            continue
        topics = item["semantic_payload"].get("topics") or []
        if query["topics"] and not set(query["topics"]) & set(topics) \
                and query["entity"] is None:
            continue
        out.append({"classification": PENDING_BINDING, "confirmed": False,
                    "reason": item["reason"], "pending_id": item["pending_id"],
                    "pending_type": kind, "entity": item["entity"], "slot": item["slot"],
                    "contexts": item["contexts"], "proposed": item["semantic_payload"],
                    "candidate_targets": item["candidate_targets"],
                    "missing_conditions": item["missing_conditions"],
                    "source_refs": item["source_refs"], "created_at": item["created_at"],
                    "uncertainty": {"classification": PENDING_BINDING, "confirmed": False,
                                    "missing_conditions": item["missing_conditions"]}})
    return out


def _view(db, identity: dict, record: dict, topics: list[str] | None = None) -> dict:
    """One revision rendered as a result row, with its own evidence and validity window."""
    return {"memory_id": identity["memory_id"], "entity": identity["entity"],
            "slot": identity["slot"], "contexts": identity["contexts"],
            "semantic_type": record["semantic_type"], "value": record["value"],
            "status": record["status"], "lifecycle": record["lifecycle"],
            "revision": record["revision"], "source_refs": record["source_refs"],
            "effective_at": record["effective_at"], "recorded_at": record["recorded_at"],
            "valid_from": record.get("valid_from"),
            "topics": (identities.topics_of(db, identity["memory_id"])
                       if topics is None else topics),
            "paths": tree.paths_of(db, identity["memory_id"])}


def _expanded(db, results: list[dict], query: dict) -> tuple[list[dict], list[str]]:
    """Reachable neighbours are added as UNKNOWN; the edge that reached them is kept."""
    origins = [relations.memory_ref(item["memory_id"]) for item in results
               if item["classification"] == CURRENT_CONFIRMED and item.get("memory_id")]
    if not origins:
        return [], []
    kinds = query["relation_kinds"] or RELATION_KINDS
    walked = relations.expand(db, origins, depth=query["expand"], kinds=kinds,
                              confirmed_only=True)
    known = {item.get("memory_id") for item in results}
    additions, nodes = [], []
    for edge in walked["edges"]:
        kind, value = relations.split_ref(edge["ref"])
        related = {"from": edge["from"], "kind": edge["kind"], "depth": edge["depth"],
                   "rel_id": edge["rel_id"]}
        if kind == "node":
            if value not in nodes:
                nodes.append(value)
            continue
        if kind != "memory" or value in known:
            continue
        known.add(value)
        identity = identities.identity_row(db, value)
        record = state.head(db, value)
        if record is None:
            continue
        item = _view(db, identity, record)
        item.update({"classification": UNKNOWN, "confirmed": False,
                     "reason": "relation_expansion", "related": related,
                     "uncertainty": {"classification": UNKNOWN, "confirmed": False,
                                     "missing_conditions": ["relation_confirmation"]}})
        additions.append(item)
    return additions, nodes


def _as_of(db, memory_id: str, instant: str) -> dict | None:
    """The revision in effect at the instant, with an explicit validity anchor first."""
    return as_of(state.revisions(db, memory_id), instant)


def _bulk_topics(db, memory_ids: list[str]) -> dict[str, list[str]]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    out: dict[str, list[str]] = {}
    for row in db.execute(f"SELECT memory_id, topic FROM memory_topics "
                          f"WHERE memory_id IN ({marks}) ORDER BY memory_id, topic", memory_ids):
        out.setdefault(row["memory_id"], []).append(row["topic"])
    return out


def _bulk_heads(db, memory_ids: list[str]) -> dict[str, dict]:
    """Every head in one query: retrieval ranks all identities, so one query per row is
    the difference between a search and a few hundred round trips."""
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    return {row["memory_id"]: json.loads(row["data"]) for row in db.execute(
        f"SELECT h.memory_id AS memory_id, r.data AS data FROM heads h "
        f"JOIN revisions r ON r.memory_id = h.memory_id AND r.revision = h.current_revision "
        f"WHERE h.memory_id IN ({marks})", memory_ids)}


def _bulk_revisions(db, memory_ids: list[str]) -> dict[str, list[dict]]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    out: dict[str, list[dict]] = {}
    for row in db.execute(f"SELECT memory_id, data FROM revisions WHERE memory_id IN ({marks}) "
                          f"ORDER BY memory_id, revision", memory_ids):
        out.setdefault(row["memory_id"], []).append(json.loads(row["data"]))
    return out


def _lexical_scored(db, text: str, until: str | None = None) -> list[tuple]:
    wanted = _terms(text)
    require(wanted, "search_text_empty")
    wanted_set = set(wanted)
    identities_by_id = [(row["memory_id"], json.loads(row["data"])) for row in
                        db.execute("SELECT memory_id, data FROM identities")]
    live = [(memory_id, identity) for memory_id, identity in identities_by_id
            if not identity.get("merged_into")]
    memory_ids = [memory_id for memory_id, _ in live]
    topics = _bulk_topics(db, memory_ids)
    if until:
        revisions = _bulk_revisions(db, memory_ids)
        records = {memory_id: as_of(items, until)
                   for memory_id, items in revisions.items()}
    else:
        records = _bulk_heads(db, memory_ids)
    scored = []
    for memory_id, identity in live:
        # ``until`` answers "as of then": a memory that only came into being later must not
        # compete for the budget, and a value superseded since must be read at its old revision.
        record = records.get(memory_id)
        if record is None:
            continue
        haystack = " ".join((identity["entity"], identity["slot"],
                             str(record["value"] or ""), " ".join(topics.get(memory_id, []))))
        hits = len(wanted_set & set(_terms(haystack)))
        if hits:
            scored.append((hits, memory_id, identity, record))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def _matched(db, identity: dict, record: dict, *, reason: str, score: float) -> dict:
    item = _view(db, identity, record)
    classification = record.get("certainty", CURRENT_CONFIRMED)
    confirmed = classification == CURRENT_CONFIRMED
    item.update({"classification": classification, "confirmed": confirmed,
                 "reason": reason, "score": score,
                 "uncertainty": {"classification": classification, "confirmed": confirmed,
                                 "missing_conditions": []}})
    return item


def _payload(text: str, results: list[dict]) -> dict:
    return {"query": {"text": text}, "results": results,
            "counts": {label: sum(row["classification"] == label for row in results)
                       for label in {CURRENT_CONFIRMED, *(row["classification"] for row in results)}}}


def _hybrid(db, text: str, scored: list[tuple], limit: int) -> dict:
    """Reciprocal-rank fusion of lexical and vector candidates: exact terms keep their weight,
    paraphrases still surface. Rank-based, so the two scales never need calibration."""
    from . import vector

    semantic = vector.search(db, text, limit=max(limit * 3, 60))
    rank_lexical = {row[1]: index for index, row in enumerate(scored)}
    rank_vector = {item["memory_id"]: index for index, item in enumerate(semantic["results"])}
    fused = {memory_id: 1.0 / (60 + rank_lexical.get(memory_id, 10 ** 6))
             + 1.0 / (60 + rank_vector.get(memory_id, 10 ** 6))
             for memory_id in set(rank_lexical) | set(rank_vector)}
    by_id = {item["memory_id"]: item for item in semantic["results"]}
    lexical_by_id = {row[1]: (row[2], row[3]) for row in scored}
    results = []
    for memory_id, score in sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        item = by_id.get(memory_id)
        if item is None:
            identity, record = lexical_by_id[memory_id]
            item = _matched(db, identity, record, reason="hybrid_match",
                            score=round(score, 5))
        else:
            item["reason"] = "hybrid_match"
            item["score"] = round(score, 5)
        results.append(item)
    return _payload(text, results)


def _anchors(identity: dict, record: dict) -> dict:
    """The filterable anchors of one candidate, before it is ranked."""
    return {"entity": identity["entity"], "contexts": identity["contexts"],
            "lifecycle": record.get("lifecycle"), "status": record.get("status"),
            "effective_at": record.get("effective_at"), "valid_from": record.get("valid_from")}


def search(db, text: str, limit: int = 20, *, entities=None, contexts=None, lifecycle=None,
           status=None, window=None, diverse: bool = False, hops: int = 1) -> dict:
    """Candidate discovery: lexical by default, vector when enabled, RRF fusion in hybrid mode.

    Anchors are filters, not ranking hints: a candidate that fails one is dropped before the
    limit is spent, so the caller's budget never goes to a memory it excluded.
    """
    from . import diversity, filters, multihop

    if hops and hops > 1 and filters.enabled("multihop"):
        return multihop.explore(db, text, limit, hops=hops, diverse=diverse,
                               entities=entities, contexts=contexts, lifecycle=lifecycle,
                               status=status, window=window)
    mode = recall_mode()
    if mode == "vector":
        from . import vector

        return vector.search(db, text, limit=limit, entities=entities, contexts=contexts,
                             lifecycle=lifecycle, status=status, window=window, diverse=diverse)
    anchors = {"entities": entities, "contexts": contexts, "lifecycle": lifecycle,
               "status": status, "window": window}
    scored = _lexical_scored(db, text, window[1] if window else None)
    if any(value is not None for value in anchors.values()) and filters.enabled("filters"):
        scored = [row for row in scored if filters.keep(_anchors(row[2], row[3]), **anchors)[0]]
    pool = limit * 3 if (diverse and filters.enabled("diversity")) else limit
    if mode != "hybrid":
        results = [_matched(db, identity, record, reason="lexical_match", score=hits)
                   for hits, _, identity, record in scored[:pool]]
    else:
        results = _hybrid(db, text, scored, pool)["results"]
    if filters.enabled("filters"):
        for item in results:
            classification, reason = filters.classify(item, item.get("revision"))
            if classification != CURRENT_CONFIRMED:
                item.update({"classification": classification, "confirmed": False,
                             "reason": reason,
                             "uncertainty": {"classification": classification,
                                             "confirmed": False, "missing_conditions": []}})
    if diverse and filters.enabled("diversity") and len(results) > limit:
        results = diversity.mmr(results, limit, text_of=lambda item: item.get("value"),
                                score_of=lambda item: float(item.get("score") or 0.0))
    return _payload(text, results[:limit])


def query(db, query: dict) -> dict:
    from . import aliases, filters

    if query["entity"] is not None and filters.enabled("alias"):
        query = {**query, "entities": aliases.links(db, query["entity"])}
    candidates = _candidate_identities(db, query)
    memory_ids = [identity["memory_id"] for identity in candidates]
    marks = ",".join("?" * len(memory_ids))
    projections = ({row["memory_id"]: json.loads(row["data"]) for row in db.execute(
        f"SELECT memory_id, data FROM projection WHERE memory_id IN ({marks})", memory_ids)}
        if memory_ids else {})
    revisions = _bulk_revisions(db, memory_ids) if query["valid_at"] is not None else {}
    topics = _bulk_topics(db, memory_ids)
    results = []
    for identity in candidates:
        memory_id = identity["memory_id"]
        require(memory_id in projections, "projection_missing")
        current = projections[memory_id]
        matched, reason = _matches(identity, query)
        if identity.get("merged_into"):
            # A retired identity keeps its revisions readable, but its value is history:
            # the live memory is the merge target, never this row.
            results.append({"classification": HISTORICAL, "confirmed": False,
                            "reason": "merged_into", **current,
                            "merged_into": identity["merged_into"],
                            "uncertainty": {"classification": HISTORICAL, "confirmed": False,
                                            "missing_conditions": []}})
            continue
        record, view_reason = current, reason
        if query["valid_at"] is not None:
            chosen = as_of(revisions.get(memory_id, []), query["valid_at"])
            if chosen is None:
                if matched:
                    # Report a known identity with unknown state; no future value or
                    # future evidence is exposed as an answer about this instant.
                    results.append({"classification": UNKNOWN, "confirmed": False,
                                    "reason": "valid_at_outside_history",
                                    "memory_id": memory_id, "entity": identity["entity"],
                                    "slot": identity["slot"], "contexts": identity["contexts"],
                                    "valid_at": query["valid_at"], "source_refs": [],
                                    "uncertainty": {"classification": UNKNOWN,
                                                    "confirmed": False,
                                                    "missing_conditions": ["valid_at_evidence"]}})
                continue
            record = chosen
            view_reason = ("valid_at_current" if matched
                           and chosen["revision"] == current["revision"]
                           else "valid_at_historical" if matched else reason)
        classification = (CURRENT_CONFIRMED if matched and record["revision"]
                          == current["revision"] else HISTORICAL if matched else UNKNOWN)
        if classification == CURRENT_CONFIRMED:
            classification = record.get("certainty", CURRENT_CONFIRMED)
        item = {"classification": classification, "confirmed": classification == CURRENT_CONFIRMED,
                "reason": view_reason,
                **_view(db, identity, record, topics.get(memory_id, [])),
                "uncertainty": {"classification": classification,
                                "confirmed": classification == CURRENT_CONFIRMED,
                                "missing_conditions": []}}
        if query["valid_at"] is not None and classification == HISTORICAL:
            item["valid_at"] = query["valid_at"]
        if query["include_dependencies"] and classification == CURRENT_CONFIRMED:
            item["dependencies"] = domain.impact(db, memory_id)
        results.append(item)
        if matched and query["include_history"]:
            for entry in state.timeline(db, memory_id):
                if entry["revision"] == record["revision"]:
                    continue
                results.append({"classification": HISTORICAL, "confirmed": False,
                                "reason": "superseded", "memory_id": memory_id,
                                "entity": identity["entity"], "slot": identity["slot"],
                                "contexts": identity["contexts"],
                                "semantic_type": entry["semantic_type"],
                                "value": entry["value"], "status": entry["status"],
                                "lifecycle": entry["lifecycle"], "revision": entry["revision"],
                                "superseded_by": record["revision"],
                                "source_refs": entry["source_refs"],
                                "effective_at": entry["effective_at"],
                                "recorded_at": entry["recorded_at"],
                                "valid_from": entry.get("valid_from"),
                                "valid_to": entry.get("valid_to"),
                                "paths": tree.paths_of(db, memory_id),
                                "uncertainty": {"classification": HISTORICAL,
                                                "confirmed": False,
                                                "missing_conditions": []}})
    expanded_nodes = []
    if query["expand"]:
        additions, expanded_nodes = _expanded(db, results, query)
        results.extend(additions)
    if query["include_pending"]:
        results.extend(_pending_matches(db, query))
    for item in results:
        item.setdefault("uncertainty", {"classification": item["classification"],
                                        "confirmed": bool(item.get("confirmed")),
                                        "missing_conditions": []})
        item["rank"] = (len(item.get("source_refs") or [])
                        + (1 if item.get("confirmed") else 0)
                        + (item.get("revision") or 0) / 1000)
    wanted = set(_terms(query["text"])) if query.get("text") else set()
    order = AS_OF_ORDER if query["valid_at"] is not None else CLASS_ORDER
    if wanted:
        # Evidence count is a popularity prior: a memory cited once but on point loses the
        # truncation to a generic memory cited five times. When the caller brings the
        # question, relevance decides and evidence count only breaks ties.
        for item in results:
            haystack = " ".join((str(item.get("entity") or ""), str(item.get("slot") or ""),
                                 str(item.get("value") or ""),
                                 " ".join(item.get("topics") or [])))
            item["lexical_hits"] = len(wanted & set(_terms(haystack)))
        results.sort(key=lambda item: (order[item["classification"]],
                                       -item["lexical_hits"], -item["rank"],
                                       item.get("memory_id", ""), item.get("revision", 0)))
    else:
        results.sort(key=lambda item: (order[item["classification"]], -item["rank"],
                                       item.get("memory_id", ""), item.get("revision", 0)))
    counts = {}
    for item in results:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return {"query": query, "counts": counts, "results": results[:query["limit"]],
            "truncated": len(results) > query["limit"],
            "expanded_nodes": expanded_nodes}


def read(db, memory_id: str, *, history: bool = False) -> dict:
    identity = identities.identity_row(db, memory_id)
    current = state.head(db, memory_id)
    stored = db.execute("SELECT data FROM projection WHERE memory_id = ?",
                        (memory_id,)).fetchone()
    require(stored is not None, "projection_missing")
    items = state.revisions(db, memory_id)
    result = {"identity": identity, "current": json.loads(stored["data"]),
              "head_revision": None if current is None else current["revision"],
              "revision_count": len(items),
              "paths": tree.paths_of(db, memory_id),
              "relations": relations.graph_of(db, memory_id),
              "identity_changes": identity_ops.changes(db, memory_id),
              "reinterpretations": [item for item in identity_ops.changes(db, memory_id)
                                    if item.get("kind") == "reinterpret"]}
    if history:
        result["history"] = state.timeline(db, memory_id)
    return result
