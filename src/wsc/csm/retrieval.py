"""Deterministic retrieval over property identities, indexed terms and source evidence.

There is no pending pool, no relation walk, no tree scope and no heuristic filter: a row is
either a memory the index reached or it is absent. Every row carries the source event excerpt
it came from, so an answer is grounded in what was said, not only in what was projected.

As-of selection uses the single event-time timeline (``valid_from``); ``recorded_at`` never
selects a value. A coding caller may anchor on a commit instead of an instant. Scopes widen
from branch to repository to entity, and the most specific state definition wins.
"""
from __future__ import annotations

import json

from . import commits, evidence
from . import identity as identities
from . import index
from . import scope as scopes
from . import state
from . import symbols
from .contracts import CURRENT_CONFIRMED, HISTORICAL, UNKNOWN, parse_instant, require

EVIDENCE_CHARS = 700
# Symbol-index contribution to candidate ordering. Adopted at 1.0 after the five-repository
# A/B: every repository held or improved R@10 and commit hit. Zero restores term-only order.
SYMBOL_WEIGHT = 1.0
# Optional ceiling on one revision's symbol score. Zero keeps the raw sum; a positive cap
# stops a commit with many diff identifiers from outranking a strong term match.
SYMBOL_CAP = 0.0
# Candidate-level gate: symbols are consulted only when the lexical candidate pool is thin.
# A zero value disables that half of the gate; both zero means symbols are always consulted.
SYMBOL_GATE_K = 0
SYMBOL_GATE_SCORE = 0.0


def _view(identity: dict, record: dict, topics: list[str]) -> dict:
    """One revision rendered as a result row; the identity supplies the anchors."""
    item = {"memory_id": identity["memory_id"], "entity": identity["entity"],
            "slot": identity["slot"], "contexts": identity["contexts"],
            "property_id": identity.get("property_id"),
            "property_kind": identity.get("property_kind"), "scope": identity.get("scope"),
            "origin_scope": scopes.origin(identity),
            "semantic_type": record["semantic_type"], "value": record["value"],
            "status": record["status"], "lifecycle": record["lifecycle"],
            "revision": record["revision"], "source_refs": record["source_refs"],
            "effective_at": record["effective_at"], "recorded_at": record["recorded_at"],
            "valid_from": record.get("valid_from"), "topics": topics}
    if record.get("commit"):
        item["commit"] = record["commit"]
    return item


def _matched_view(identity: dict, record: dict, topics: list[str], *, classification: str,
                  reason: str, score: float | None = None) -> dict:
    item = _view(identity, record, topics)
    item.update({"classification": classification,
                 "confirmed": classification == CURRENT_CONFIRMED,
                 "reason": reason})
    if score is not None:
        item["score"] = score
    return item


def _allows(identity: dict, *, entity: str | None, scope: str | None,
            widen: bool) -> bool:
    """Anchors are filters: a candidate that fails one is dropped before the limit is spent."""
    if entity is not None and identity["entity"] != entity:
        return False
    return scopes.allows(scopes.origin(identity), scope, widen=widen)


def _matches(identity: dict, query: dict) -> bool:
    if query["slot"] is not None and identity["slot"] != query["slot"]:
        return False
    return _allows(identity, entity=query["entity"], scope=query["scope"],
                   widen=query["scope_chain"])


def _topic_map(db, memory_ids: list[str]) -> dict[str, list[str]]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    out: dict[str, list[str]] = {}
    for row in db.execute(f"SELECT memory_id, topic FROM memory_topics "
                          f"WHERE memory_id IN ({marks}) ORDER BY memory_id, topic", memory_ids):
        out.setdefault(row["memory_id"], []).append(row["topic"])
    return out


def _identity_rows(db, memory_ids: list[str]) -> dict[str, dict]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    return {row["memory_id"]: json.loads(row["data"]) for row in
            db.execute(f"SELECT memory_id, data FROM identities "
                       f"WHERE memory_id IN ({marks}) ORDER BY memory_id", memory_ids)}


def _candidate_ids(db, query: dict) -> list[str]:
    """Anchored candidates; a text query ranks them, it never widens them."""
    if query["entity"] is not None or query["slot"] is not None:
        clauses, params = [], []
        if query["entity"] is not None:
            clauses.append("entity = ?")
            params.append(query["entity"])
        if query["slot"] is not None:
            clauses.append("slot = ?")
            params.append(query["slot"])
        return [row["memory_id"] for row in
                db.execute(f"SELECT memory_id FROM identities WHERE {' AND '.join(clauses)} "
                           "ORDER BY memory_id", params)]
    if query["topics"]:
        marks = ",".join("?" * len(query["topics"]))
        return [row["memory_id"] for row in
                db.execute(f"SELECT DISTINCT memory_id FROM memory_topics "
                           f"WHERE topic IN ({marks}) ORDER BY memory_id", list(query["topics"]))]
    return []


def _ranked(db, query: dict, ids: list[str], records: dict[str, dict]) -> list[str]:
    """Term score first (plus the symbol score when enabled), then the event-time order."""
    if query["text"] and ids:
        score = index.scores(db, query["text"], ids, symbol_weight=SYMBOL_WEIGHT,
                              symbol_cap=SYMBOL_CAP, symbol_gate_k=SYMBOL_GATE_K,
                              symbol_gate_score=SYMBOL_GATE_SCORE)
        if score:
            return sorted(ids, key=lambda memory_id: (-score.get(memory_id, 0), memory_id))
    return sorted(ids, key=lambda memory_id: (
        _sort_time(records.get(memory_id) or {}), memory_id), reverse=True)


def _sort_time(record: dict) -> float:
    value = record.get("valid_from") or record.get("effective_at") or record.get("recorded_at")
    if not value:
        return 0.0
    try:
        return parse_instant(value).timestamp()
    except ValueError:
        return 0.0


def _state_overrides(rows: list[dict], query: dict,
                     records: dict[str, dict] | None = None
                     ) -> tuple[list[dict], dict[str, int]]:
    """At a widened scope the most specific state definition in effect wins.

    A branch identity that only appears later must not hide the repository value at an
    earlier instant, so selection prefers the most specific row that has a revision in
    effect; when none does, one representative is kept so the caller can still see UNKNOWN.
    """
    if not query["scope"]:
        return rows, {}
    specificity = {row["memory_id"]: scopes.specificity(
        scopes.origin(row), query["scope"], widen=query["scope_chain"]) for row in rows}
    groups: dict[tuple, list[dict]] = {}
    keep = []
    for row in rows:
        if row.get("property_kind") == "event":
            keep.append(row)
            continue
        groups.setdefault((row["entity"], row.get("property_id") or row["slot"]),
                          []).append(row)
    for group in groups.values():
        available = [row for row in group
                     if records is None or records.get(row["memory_id"]) is not None]
        chosen = min(available or group, key=lambda row: specificity[row["memory_id"]])
        keep.append(chosen)
    return keep, specificity


def query(db, query: dict) -> dict:
    """Lookup by identity anchors; ``valid_at`` or ``at_commit`` selects the revision in effect."""
    instant = query["valid_at"]
    if query["at_commit"]:
        instant = commits.instant(db, query["at_commit"])
    rows = _identity_rows(db, _candidate_ids(db, query))
    selected = [row for row in rows.values() if _matches(row, query)]
    candidate_ids = [row["memory_id"] for row in selected]
    if instant:
        records = index.as_of_records(db, candidate_ids, instant)
    else:
        records = index.head_records(db, candidate_ids)
    selected, specificity = _state_overrides(selected, query, records)
    ids = [row["memory_id"] for row in selected]
    records = {memory_id: records[memory_id] for memory_id in ids if memory_id in records}
    ranked = _ranked(db, query, ids, records)
    if specificity:
        ranked.sort(key=lambda memory_id: specificity.get(memory_id, 0))
    topics = _topic_map(db, ranked)
    heads = index.head_numbers(db, ids)
    results = []
    for memory_id in ranked[:query["limit"]]:
        identity = rows[memory_id]
        record = records.get(memory_id)
        if record is None:
            if instant:
                # The identity exists but has no revision in effect at the instant. Report the
                # anchor without inventing a value or a future piece of evidence.
                results.append({"memory_id": memory_id, "entity": identity["entity"],
                                "slot": identity["slot"], "contexts": identity["contexts"],
                                "property_id": identity.get("property_id"),
                                "property_kind": identity.get("property_kind"),
                                "scope": identity.get("scope"),
                                "origin_scope": scopes.origin(identity),
                                "valid_at": instant, "source_refs": [],
                                "classification": UNKNOWN, "confirmed": False,
                                "reason": "valid_at_outside_history"})
            continue
        current = heads.get(memory_id) == record["revision"]
        classification = CURRENT_CONFIRMED if current or not instant else HISTORICAL
        reason = ("identity_match" if not instant
                  else "valid_at_current" if current else "valid_at_historical")
        item = _matched_view(identity, record, topics.get(memory_id, []),
                             classification=classification, reason=reason)
        if instant:
            item["valid_at"] = instant
        if query["at_commit"]:
            item["at_commit"] = query["at_commit"]
        results.append(item)
        if query["include_history"]:
            for entry in state.timeline(db, memory_id):
                if entry["revision"] == record["revision"]:
                    continue
                results.append({**_matched_view(identity, entry, topics.get(memory_id, []),
                                               classification=HISTORICAL,
                                               reason="superseded"),
                                "superseded_by": record["revision"]})
    if query["with_evidence"]:
        evidence.attach(db, results, max_chars=EVIDENCE_CHARS)
    return {"query": {key: query[key] for key in
                      ("entity", "slot", "topics", "scope", "scope_chain", "valid_at",
                       "at_commit", "text")},
            "results": results,
            "counts": {label: sum(row["classification"] == label for row in results)
                       for label in (CURRENT_CONFIRMED, HISTORICAL, UNKNOWN)}}


def _window_end(window) -> str | None:
    if not window:
        return None
    return window[1] if len(window) > 1 else window[0]


def search(db, text: str, limit: int = 20, *, window=None, entity: str | None = None,
           scope: str | None = None, scope_chain: bool = False,
           at_commit: str | None = None, with_evidence: bool = True,
           anchor: str | None = None, anchor_terms: int = symbols.ANCHOR_TERMS) -> dict:
    """Term-indexed candidate discovery; the cutoff selects each row at its past revision.

    ``anchor`` is optional code the caller is working on. Its identifiers are added as query
    keys, so a phrase-free query still reaches revisions whose diffs contain them.
    """
    require(bool(text and str(text).strip()), "search_text_empty")
    require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0,
            "query_limit_invalid")
    if anchor:
        extra = symbols.query_terms(str(anchor), limit=anchor_terms)
        if extra:
            text = f"{text} {' '.join(extra)}"
    until = _window_end(window)
    if at_commit:
        until = commits.instant(db, at_commit)
    ids = index.candidates(db, text, limit=max(limit * 8, 80), head_only=until is None,
                           symbol_weight=SYMBOL_WEIGHT, symbol_cap=SYMBOL_CAP,
                           symbol_gate_k=SYMBOL_GATE_K,
                           symbol_gate_score=SYMBOL_GATE_SCORE)
    rows = _identity_rows(db, ids)
    ids = [memory_id for memory_id in ids
           if memory_id in rows and _allows(rows[memory_id], entity=entity, scope=scope,
                                            widen=scope_chain)]
    records = index.as_of_records(db, ids, until) if until else index.head_records(db, ids)
    if scope and ids:
        kept, _ = _state_overrides([rows[memory_id] for memory_id in ids],
                                   {"scope": scope, "scope_chain": scope_chain}, records)
        keep = {row["memory_id"] for row in kept}
        ids = [memory_id for memory_id in ids if memory_id in keep]
        records = {memory_id: records[memory_id] for memory_id in ids if memory_id in records}
    topics = _topic_map(db, ids)
    results = []
    for memory_id in ids:
        record = records.get(memory_id)
        if record is None:
            continue
        item = _matched_view(rows[memory_id], record, topics.get(memory_id, []),
                             classification=CURRENT_CONFIRMED, reason="term_match")
        if until:
            item["as_of"] = until
        results.append(item)
    results = results[:limit]
    if with_evidence:
        evidence.attach(db, results, max_chars=EVIDENCE_CHARS)
    return {"query": {"text": str(text), "window": until, "entity": entity,
                      "scope": scope, "scope_chain": scope_chain, "at_commit": at_commit},
            "results": results,
            "counts": {CURRENT_CONFIRMED: len(results)}}


def read(db, memory_id: str, *, history: bool = False) -> dict:
    """One memory as its current projection plus, optionally, its full revision timeline."""
    identity = identities.identity_row(db, memory_id)
    topics = identities.topics_of(db, memory_id)
    head = state.head(db, memory_id)
    if head is None:
        return {"memory_id": memory_id, "entity": identity["entity"],
                "slot": identity["slot"], "contexts": identity["contexts"],
                "property_id": identity.get("property_id"),
                "property_kind": identity.get("property_kind"),
                "scope": identity.get("scope"), "revisions": 0}
    item = _matched_view(identity, head, topics, classification=CURRENT_CONFIRMED,
                         reason="head")
    evidence.attach(db, [item], max_chars=EVIDENCE_CHARS)
    packet = {**item, "revisions": head["revision"], "history": []}
    if history:
        packet["history"] = state.timeline(db, memory_id)
    return packet


__all__ = ["query", "search", "read", "EVIDENCE_CHARS"]
