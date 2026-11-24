"""Identity resolution over engine-owned properties, never over string similarity.

A candidate binds to a property record; the key is ``entity + property_id + scope``. State
properties live at entity scope and update; event properties live at their own observation
scope, so distinct observations cannot overwrite each other.
"""
from __future__ import annotations

import json

from ..contracts import digest, encode
from . import properties
from . import scope as scopes
from .contracts import IDENTITY_KEY_RULE, identity_key, memory_id_for, require


def identity_row(db, memory_id: str) -> dict:
    row = db.execute("SELECT data FROM identities WHERE memory_id = ?", (memory_id,)).fetchone()
    require(row is not None, "memory_identity_unknown")
    return json.loads(row["data"])


def topics_of(db, memory_id: str) -> list[str]:
    return [row["topic"] for row in
            db.execute("SELECT topic FROM memory_topics WHERE memory_id = ? ORDER BY topic",
                       (memory_id,))]


def symbols_of(db, memory_id: str) -> list[str]:
    """Index keys derived from changed code, never identity anchors."""
    return [row["symbol"] for row in
            db.execute("SELECT symbol FROM memory_symbols WHERE memory_id = ? ORDER BY symbol",
                       (memory_id,))]


def _event_scope(data: dict) -> str:
    source = (data.get("source_ids") or ("unknown",))[0]
    marker = digest(encode(data.get("value")))[:8]
    return f"event:{source}:{marker}"


def scope_for(data: dict, item: dict) -> str:
    """Event facts partition per observation; state facts live at the requested scope."""
    if item["kind"] == "event":
        return _event_scope(data)
    return scopes.origin(data)


def route(db, data: dict, *, recorded_at: str = "") -> dict:
    """Bind one validated candidate to its property and identity; CREATE or UPDATE only."""
    item = properties.resolve(db, data["entity"], data["slot"], kind=data.get("property_kind"),
                              scope=data.get("scope"), recorded_at=recorded_at)
    scope = scope_for(data, item)
    key = identity_key(data["entity"], item["property_id"], scope)
    row = db.execute("SELECT memory_id, data FROM identities WHERE identity_key = ?",
                     (key,)).fetchone()
    if row is not None:
        return {"operation": "UPDATE", "memory_id": row["memory_id"], "property": item,
                "scope": scope, "origin_scope": scopes.origin(data),
                "reason": "identity_match",
                "merged_into": json.loads(row["data"]).get("merged_into")}
    return {"operation": "CREATE", "property": item, "scope": scope,
            "origin_scope": scopes.origin(data),
            "memory_id": memory_id_for(data["entity"], item["property_id"], scope),
            "reason": "identity_new"}


def create(db, data: dict, item: dict, scope: str, *, origin_scope: str,
           producer: str, recorded_at: str) -> dict:
    memory_id = memory_id_for(data["entity"], item["property_id"], scope)
    payload = {"memory_id": memory_id,
               "identity_key": identity_key(data["entity"], item["property_id"], scope),
               "identity_key_rule": IDENTITY_KEY_RULE,
               "entity": data["entity"], "slot": item["name"],
               "property_id": item["property_id"], "property_kind": item["kind"],
               "scope": scope, "origin_scope": origin_scope,
               "contexts": list(data["contexts"]),
               "semantic_type": data["semantic_type"],
               "identity_evidence": list(data["source_ids"]),
               "created_at": recorded_at, "producer": producer}
    db.execute("INSERT INTO identities(memory_id, identity_key, entity, slot, contexts, "
               "semantic_type, data, property_id, property_kind, scope) "
               "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (memory_id, payload["identity_key"], payload["entity"], payload["slot"],
                json.dumps(payload["contexts"]), payload["semantic_type"],
                json.dumps(payload, sort_keys=True, ensure_ascii=False),
                payload["property_id"], payload["property_kind"], payload["scope"]))
    for topic in data["topics"]:
        db.execute("INSERT OR IGNORE INTO memory_topics(memory_id, topic) VALUES(?, ?)",
                   (memory_id, topic))
    for symbol in data.get("symbols") or ():
        db.execute("INSERT OR IGNORE INTO memory_symbols(memory_id, symbol) VALUES(?, ?)",
                   (memory_id, symbol))
    return payload


def add_symbols(db, memory_id: str, symbols: tuple[str, ...]) -> dict:
    added = []
    for symbol in symbols:
        cursor = db.execute("INSERT OR IGNORE INTO memory_symbols(memory_id, symbol) "
                            "VALUES(?, ?)", (memory_id, symbol))
        if cursor.rowcount:
            added.append(symbol)
    return {"memory_id": memory_id, "symbols": symbols_of(db, memory_id), "added_symbols": added}


def add_topics(db, memory_id: str, topics: tuple[str, ...]) -> dict:
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
                   (json.dumps(data, sort_keys=True, ensure_ascii=False), memory_id))
    return {"memory_id": memory_id, "topics": topics_of(db, memory_id), "added_topics": added}


__all__ = ["identity_row", "live", "topics_of", "add_topics", "symbols_of", "add_symbols",
           "route", "create", "scope_for"]
