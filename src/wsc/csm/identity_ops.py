"""Rekey, merge and reinterpret: the only three ways an identity's anchors may change.

The identity key is ``entity + slot + declared context set`` (``IDENTITY_KEY_RULE``),
so changing a declared context is not an edit of a field — it is a different identity.
Three operations cover it, all evidence-gated and none rewriting a committed revision:

``rekey``
    The same memory was described with the wrong declared context set (typically: it was
    created without an anchor and later evidence names one). The identity keeps its
    ``memory_id`` label, adopts the new context set, and stays the same memory: its
    revisions, projection and topics are untouched apart from the anchors themselves.

``merge``
    Two live identities with the same entity and slot turn out to be one memory. The
    target stays live, the source is retired with ``merged_into``: its revisions and
    projection stay readable as history, and new evidence at the source's anchors is
    routed to the target. Nothing is deleted, nothing is renumbered.

``reinterpret``
    New evidence changes what an existing declared context set *means*, without the
    memory becoming a different memory. The identity keeps its ``memory_id``, revisions
    and history; the previous anchors stay readable in ``reinterpretations`` and the
    correction must state its reason, because a guess about intent is not a correction.

Evidence requirement: both operations require at least one already-ingested source event
that supports the new anchor interpretation, and unknown events are rejected. Similarity,
shared topics or a matching value are not evidence.
"""
from __future__ import annotations

import json

from . import identity as identities
from . import state
from .contracts import CSMError, IDENTITY_KEY_RULE, anchors, identity_key


def _require(condition: bool, code: str) -> None:
    """Anchor violations are CSM results, not generic contract failures."""
    if not condition:
        raise CSMError(code)


def _evidence(db, source_ids, *, code: str = "identity_evidence_missing") -> list[str]:
    ids = [item for item in source_ids if item]
    _require(ids, code)
    marks = ",".join("?" * len(ids))
    found = {row["id"] for row in
             db.execute(f"SELECT id FROM events WHERE id IN ({marks})", ids)}
    _require(all(item in found for item in ids), "evidence_source_unknown")
    return ids


def _log(db, memory_id: str, kind: str, payload: dict, recorded_at: str) -> None:
    db.execute("INSERT INTO identity_changes(memory_id, kind, recorded_at, data) "
               "VALUES(?, ?, ?, ?)",
               (memory_id, kind, recorded_at,
                json.dumps(payload, sort_keys=True, ensure_ascii=False)))


def changes(db, memory_id: str) -> list[dict]:
    return [{"kind": row["kind"], "recorded_at": row["recorded_at"],
             **json.loads(row["data"])}
            for row in db.execute("SELECT kind, recorded_at, data FROM identity_changes "
                                  "WHERE memory_id = ? ORDER BY change_id", (memory_id,))]


def _store_identity(db, data: dict) -> None:
    db.execute("UPDATE identities SET identity_key = ?, contexts = ?, data = ? "
               "WHERE memory_id = ?",
               (data["identity_key"], json.dumps(data["contexts"]), 
                json.dumps(data, sort_keys=True, ensure_ascii=False), data["memory_id"]))


def _reproject(db, data: dict) -> None:
    """Rewrite the current-state view after an anchor change; the head revision stands."""
    current = state.head(db, data["memory_id"])
    _require(current is not None, "memory_revision_missing")
    payload = state.projection_payload(data, current, identities.topics_of(db, data["memory_id"]))
    db.execute("INSERT INTO projection(memory_id, data) VALUES(?, ?) "
               "ON CONFLICT(memory_id) DO UPDATE SET data = excluded.data",
               (data["memory_id"], json.dumps(payload, sort_keys=True, ensure_ascii=False)))


def _release_key(db, data: dict) -> None:
    """A retired identity must not hold a live anchor: keep the old key as history only."""
    if data.get("previous_identity_key"):
        return
    data["previous_identity_key"] = data["identity_key"]
    data["identity_key"] = f"merged:{data['memory_id']}"


def rekey(db, memory_id: str, contexts, evidence, *, producer: str = "model",
          recorded_at: str) -> dict:
    """Give an existing identity its declared context set; the memory_id label is kept."""
    data = identities.identity_row(db, memory_id)
    _require(not data.get("merged_into"), "memory_identity_merged")
    ids = _evidence(db, evidence)
    declared = list(anchors(tuple(contexts), field="context"))
    _require(declared != list(data["contexts"]), "identity_rekey_noop")
    key = identity_key(data["entity"], data["slot"], tuple(declared))
    clash = [json.loads(row["data"]) for row in
             db.execute("SELECT data FROM identities WHERE identity_key = ? AND memory_id <> ?",
                        (key, memory_id))]
    # A retired identity released its anchor, so it cannot block a live one.
    _require(not any(not item.get("merged_into") for item in clash), "identity_rekey_conflict")
    previous = list(data["contexts"])
    data["contexts"] = declared
    data["identity_key"] = key
    data["identity_key_rule"] = IDENTITY_KEY_RULE
    data["identity_evidence"] = list(dict.fromkeys([*data.get("identity_evidence", []), *ids]))
    _store_identity(db, data)
    _reproject(db, data)
    _log(db, memory_id, "rekey",
         {"previous_contexts": previous, "contexts": declared, "evidence": ids,
          "producer": producer, "identity_key_rule": IDENTITY_KEY_RULE}, recorded_at)
    return {"operation": "REKEY", "memory_id": memory_id, "previous_contexts": previous,
            "contexts": declared, "evidence": ids, "changed": True}


def merge(db, target: str, source: str, evidence, *, contexts=None, producer: str = "model",
          recorded_at: str) -> dict:
    """Retire ``source`` into ``target``: same entity and slot, one memory.

    ``contexts`` additionally converges the survivor's declared context set in the same
    transaction: the retired identity releases its anchor, the survivor takes the new one.
    Both halves share one evidence set; a failed convergence rolls the retirement back.
    """
    _require(target != source, "identity_merge_self")
    kept = identities.identity_row(db, target)
    retired = identities.identity_row(db, source)
    _require(not kept.get("merged_into"), "memory_identity_merged")
    _require(not retired.get("merged_into"), "memory_identity_merged")
    _require((kept["entity"], kept["slot"]) == (retired["entity"], retired["slot"]),
             "identity_merge_scope")
    ids = _evidence(db, evidence)
    source_key = retired["identity_key"]
    source_contexts = list(retired["contexts"])
    for topic in identities.topics_of(db, source):
        db.execute("INSERT OR IGNORE INTO memory_topics(memory_id, topic) VALUES(?, ?)",
                   (target, topic))
    # Retire before converging: the retired identity must stop holding its anchor before
    # the survivor can take it, and both stay inside one transaction.
    _release_key(db, retired)
    retired["merged_into"] = target
    retired["merged_at"] = recorded_at
    retired["merge_evidence"] = ids
    _store_identity(db, retired)
    db.execute("INSERT OR REPLACE INTO identity_aliases(identity_key, memory_id, created_at) "
               "VALUES(?, ?, ?)", (source_key, target, recorded_at))
    kept["merged_from"] = list(dict.fromkeys([*kept.get("merged_from", []), source]))
    kept["identity_evidence"] = list(dict.fromkeys([*kept.get("identity_evidence", []), *ids]))
    _store_identity(db, kept)
    _log(db, target, "merge_in",
         {"source": source, "source_contexts": source_contexts, "evidence": ids,
          "producer": producer}, recorded_at)
    _log(db, source, "merge_out", {"target": target, "evidence": ids, "producer": producer},
         recorded_at)
    converged = False
    if contexts is not None:
        declared = list(anchors(tuple(contexts), field="context"))
        if declared != list(kept["contexts"]):
            rekey(db, target, contexts, ids, producer=producer, recorded_at=recorded_at)
            converged = True
        kept = identities.identity_row(db, target)
    return {"operation": "MERGE", "memory_id": target, "merged": source,
            "source_contexts": source_contexts, "target_contexts": kept["contexts"],
            "converged": converged, "evidence": ids, "changed": True}


def reinterpret(db, memory_id: str, contexts, evidence, *, reason: str,
                producer: str = "model", recorded_at: str) -> dict:
    """Re-read what an existing memory's anchors mean in the light of new evidence (§7.4).

    This is not a rekey: the identity keeps its memory_id, its revisions and its history,
    but the new evidence changes the *interpretation* of the declared context set, so the
    old anchors stay readable as history and the correction carries a stated reason. It
    requires evidence and an explicit reason — a guess about intent is not a correction.
    """
    data = identities.identity_row(db, memory_id)
    _require(not data.get("merged_into"), "memory_identity_merged")
    _require(isinstance(reason, str) and bool(reason.strip()), "reinterpret_reason_missing")
    ids = _evidence(db, evidence)
    declared = list(anchors(tuple(contexts), field="context"))
    _require(declared != list(data["contexts"]), "identity_reinterpret_noop")
    key = identity_key(data["entity"], data["slot"], tuple(declared))
    clash = [json.loads(row["data"]) for row in
             db.execute("SELECT data FROM identities WHERE identity_key = ? AND memory_id <> ?",
                        (key, memory_id))]
    _require(not any(not item.get("merged_into") for item in clash),
             "identity_reinterpret_conflict")
    previous = list(data["contexts"])
    data["contexts"] = declared
    data["identity_key"] = key
    data["identity_key_rule"] = IDENTITY_KEY_RULE
    data["identity_evidence"] = list(dict.fromkeys([*data.get("identity_evidence", []), *ids]))
    data["reinterpretations"] = [*data.get("reinterpretations", []),
                                 {"previous_contexts": previous, "contexts": declared,
                                  "reason": reason.strip(), "evidence": ids,
                                  "recorded_at": recorded_at}]
    _store_identity(db, data)
    _reproject(db, data)
    _log(db, memory_id, "reinterpret",
         {"previous_contexts": previous, "contexts": declared, "reason": reason.strip(),
          "evidence": ids, "producer": producer}, recorded_at)
    return {"operation": "REINTERPRET", "memory_id": memory_id,
            "previous_contexts": previous, "contexts": declared, "reason": reason.strip(),
            "evidence": ids, "changed": True}


__all__ = ["rekey", "merge", "reinterpret", "changes", "CSMError"]
