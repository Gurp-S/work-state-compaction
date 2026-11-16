"""Identity resolution. Entity identity decides the memory; similarity never merges."""
from __future__ import annotations

import json

from .contracts import require
from .contracts import CSMError, IDENTITY_KEY_RULE, identity_key, memory_id_for


def identity_row(db, memory_id: str) -> dict:
    row = db.execute("SELECT data FROM identities WHERE memory_id = ?", (memory_id,)).fetchone()
    require(row is not None, "memory_identity_unknown")
    return json.loads(row["data"])


def live(db, memory_id: str) -> dict:
    """Follow merge redirects to the identity that owns new state now."""
    seen = set()
    while memory_id not in seen:
        seen.add(memory_id)
        data = identity_row(db, memory_id)
        target = data.get("merged_into")
        if not target:
            return data
        memory_id = target
    raise CSMError("identity_merge_cycle")


def topics_of(db, memory_id: str) -> list[str]:
    return [row["topic"] for row in
            db.execute("SELECT topic FROM memory_topics WHERE memory_id = ? ORDER BY topic",
                       (memory_id,))]


def siblings(db, entity: str, slot: str) -> list[dict]:
    """Live identities with the same entity and slot and other contexts: never merged."""
    return [item for item in (json.loads(row["data"]) for row in
                              db.execute("SELECT data FROM identities WHERE entity = ? AND slot = ? "
                                         "ORDER BY memory_id", (entity, slot)))
            if not item.get("merged_into")]


def route(db, candidate: dict) -> dict:
    """Deterministic CREATE / UPDATE / DEFER decision for one validated candidate.

    DEFER is the only safe answer when several live context variants exist and the
    candidate does not say which one it means: attribution is then pending, not guessed.

    ``link`` and ``reinterpret`` are not state writes: they resolve a subject identity and
    return the operation the caller asked for, so routing never silently edits a memory.
    """
    if candidate["intent"] == "link":
        target = candidate.get("target_memory_id")
        if target is None:
            key = identity_key(candidate["entity"], candidate["slot"], candidate["contexts"])
            row = db.execute("SELECT memory_id FROM identities WHERE identity_key = ?",
                             (key,)).fetchone()
            target = None if row is None else live(db, row["memory_id"])["memory_id"]
        if target is None:
            return {"operation": "DEFER", "memory_id": None, "reason": "identity_unknown",
                    "candidate_targets": [], "missing_conditions": ["identity"]}
        owner = live(db, target)
        return {"operation": "LINK", "memory_id": owner["memory_id"],
                "reason": "identity_link"}
    if candidate["intent"] == "reinterpret":
        target = candidate.get("target_memory_id")
        if target is None:
            related = siblings(db, candidate["entity"], candidate["slot"])
            target = related[0]["memory_id"] if len(related) == 1 else None
            if target is None:
                return {"operation": "DEFER", "memory_id": None,
                        "reason": "identity_ambiguous" if related else "identity_unknown",
                        "candidate_targets": [item["memory_id"] for item in related],
                        "missing_conditions": ["identity"]}
        owner = live(db, target)
        require((owner["entity"], owner["slot"]) == (candidate["entity"], candidate["slot"]),
                "identity_reinterpret_scope")
        return {"operation": "REINTERPRET", "memory_id": owner["memory_id"],
                "reason": "identity_reinterpret"}
    key = identity_key(candidate["entity"], candidate["slot"], candidate["contexts"])
    row = db.execute("SELECT memory_id FROM identities WHERE identity_key = ?", (key,)).fetchone()
    if row is not None:
        owner = live(db, row["memory_id"])
        reason = "identity_match" if owner["memory_id"] == row["memory_id"] else "identity_redirect"
        return {"operation": "UPDATE", "memory_id": owner["memory_id"], "reason": reason}
    alias = db.execute("SELECT memory_id FROM identity_aliases WHERE identity_key = ?",
                       (key,)).fetchone()
    if alias is not None:
        # A retired identity released this anchor; its evidence still belongs to the survivor.
        owner = live(db, alias["memory_id"])
        return {"operation": "UPDATE", "memory_id": owner["memory_id"],
                "reason": "identity_redirect"}
    related = siblings(db, candidate["entity"], candidate["slot"])
    if related and not candidate["contexts"] and candidate["intent"] != "create":
        # Several context variants exist and the candidate names none of them:
        # the attribution is undecidable, so it must not be guessed.
        return {"operation": "DEFER", "memory_id": None, "reason": "identity_ambiguous",
                "candidate_targets": [item["memory_id"] for item in related],
                "missing_conditions": ["context_anchor"]}
    if candidate["intent"] == "update":
        return {"operation": "DEFER", "memory_id": None, "reason": "identity_unknown",
                "candidate_targets": [], "missing_conditions": ["identity"]}
    memory_id = memory_id_for(candidate["entity"], candidate["slot"], candidate["contexts"])
    taken = db.execute("SELECT identity_key FROM identities WHERE memory_id = ?",
                       (memory_id,)).fetchone()
    if taken is not None:
        raise CSMError("memory_identity_conflict")
    return {"operation": "CREATE", "memory_id": memory_id, "reason": "identity_new"}


def create(db, candidate: dict, *, producer: str, recorded_at: str) -> dict:
    """Bind a new memory identity. Identity exists before any state revision does."""
    key = identity_key(candidate["entity"], candidate["slot"], candidate["contexts"])
    data = {"memory_id": memory_id_for(candidate["entity"], candidate["slot"], candidate["contexts"]),
            "identity_key": key, "identity_key_rule": IDENTITY_KEY_RULE,
            "entity": candidate["entity"], "slot": candidate["slot"],
            "contexts": list(candidate["contexts"]), "semantic_type": candidate["semantic_type"],
            "identity_evidence": list(candidate["source_ids"]),
            "created_at": recorded_at, "producer": producer}
    db.execute("INSERT INTO identities(memory_id, identity_key, entity, slot, contexts, "
               "semantic_type, data) VALUES(?, ?, ?, ?, ?, ?, ?)",
               (data["memory_id"], key, data["entity"], data["slot"],
                json.dumps(data["contexts"]), data["semantic_type"], json.dumps(data, sort_keys=True)))
    for topic in candidate["topics"]:
        db.execute("INSERT OR IGNORE INTO memory_topics(memory_id, topic) VALUES(?, ?)",
                   (data["memory_id"], topic))
    return data


def add_topics(db, memory_id: str, topics: tuple[str, ...]) -> dict:
    """Enrichment adds retrieval anchors only: no state revision, no identity change."""
    data = identity_row(db, memory_id)
    added = []
    for topic in topics:
        cursor = db.execute("INSERT OR IGNORE INTO memory_topics(memory_id, topic) VALUES(?, ?)",
                            (memory_id, topic))
        if cursor.rowcount:
            added.append(topic)
    if added:
        data["topics"] = topics_of(db, memory_id)
        db.execute("UPDATE identities SET data = ? WHERE memory_id = ?",
                   (json.dumps(data, sort_keys=True), memory_id))
    return {"memory_id": memory_id, "added_topics": added, "topics": topics_of(db, memory_id)}
