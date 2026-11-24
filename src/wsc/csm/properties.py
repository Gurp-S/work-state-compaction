"""Engine-owned property registry: the model binds to an identity, it does not name one.

The identity key is a function of engine-owned IDs, not free-form strings. A property is
created once per (entity, canonical name), keeps a stable id, and carries the two facts the
update semantics actually need: whether it is a durable state or a one-off observation, and
the scope it lives in.
"""
from __future__ import annotations

import json
import re

from ..contracts import digest
from .contracts import require, normalize

EPISODIC = frozenset({
    "建议", "建议做法", "提醒", "约定", "事项", "询问", "信息", "内容", "提议", "回应",
    "要求", "经历", "事件", "梦", "故事", "见闻",
    "状态", "当前状态", "情况", "当前情况", "感受", "心情", "身体感受", "想法",
})
_EPISODIC_SUFFIX = ("建议", "提醒", "约定", "事项", "询问", "提议", "状态", "情况", "感受")

# Coding vocabulary: a decision or a failure is an observation and must never overwrite an
# earlier one; toolchain and conventions are durable and update in place.
_CODING_EVENT = frozenset({
    "decision", "decisions", "constraint", "constraints", "convention", "conventions",
    "rejected", "rejection", "alternative", "alternatives", "failure", "failures",
    "incident", "incidents", "migration", "migrations", "review", "reviews", "lesson",
    "lessons", "bug", "bugs", "todo", "todos", "rationale", "tradeoff", "tradeoffs",
    "postmortem", "retro", "discussion", "observation", "observations", "note", "notes",
    "log", "logs",
})
_CODING_STATE = frozenset({
    "toolchain", "runtime", "language", "version", "branch", "package_manager",
    "build", "build_command", "test_command", "lint", "formatter", "owner", "owners",
    "env", "environment", "dependency", "dependencies", "api", "endpoint", "schema",
    "path", "module", "port", "timeout", "config",
})
_WORD = re.compile(r"[^a-z0-9]+")


def _tokens(key: str) -> set[str]:
    return {item for item in _WORD.split(key) if item}


def infer_kind(name: str) -> str:
    """Default classification for a first occurrence; a declared kind always wins."""
    key = normalize(name)
    if key in EPISODIC or key.endswith(_EPISODIC_SUFFIX):
        return "event"
    words = _tokens(key)
    if key in _CODING_EVENT or words & _CODING_EVENT:
        return "event"
    if key in _CODING_STATE or words & _CODING_STATE:
        return "state"
    return "state"


def _row(row) -> dict:
    return json.loads(row["data"])


def get(db, property_id: str) -> dict | None:
    row = db.execute("SELECT data FROM properties WHERE property_id = ?", (property_id,)).fetchone()
    return None if row is None else _row(row)


def resolve(db, entity: str, name: str, *, kind: str | None = None,
            scope: str | None = None, recorded_at: str = "") -> dict:
    """Return the property a write binds to, creating it once if this is its first sight."""
    clean = normalize(name, field="slot")
    row = db.execute("SELECT data FROM properties WHERE entity = ? AND normalized_name = ?",
                     (normalize(entity, field="entity"), clean)).fetchone()
    if row is not None:
        return _row(row)
    alias = db.execute("SELECT property_id FROM property_aliases WHERE entity = ? AND alias = ?",
                       (normalize(entity, field="entity"), clean)).fetchone()
    if alias is not None:
        found = get(db, alias["property_id"])
        if found is not None:
            return found
    chosen_kind = kind if kind in ("state", "event") else infer_kind(clean)
    property_id = "prp_" + digest({"entity": normalize(entity, field="entity"),
                                   "name": clean, "kind": chosen_kind})[:16]
    data = {"property_id": property_id, "entity": normalize(entity, field="entity"),
            "name": name.strip(), "normalized_name": clean, "kind": chosen_kind,
            "scope": scope or ("event" if chosen_kind == "event" else "entity"),
            "aliases": [], "version": 1, "created_at": recorded_at}
    db.execute("INSERT INTO properties(property_id, entity, normalized_name, kind, scope, data) "
               "VALUES(?, ?, ?, ?, ?, ?)",
               (property_id, data["entity"], clean, chosen_kind, data["scope"],
                json.dumps(data, sort_keys=True, ensure_ascii=False)))
    return data


def add_alias(db, property_id: str, alias: str) -> dict:
    """Declare one more surface name for an existing property; evidence is the caller's job."""
    item = get(db, property_id)
    require(item is not None, "property_unknown")
    clean = normalize(alias, field="slot")
    if clean == item["normalized_name"] or clean in item.get("aliases", []):
        return item
    item["aliases"] = [*item.get("aliases", []), clean]
    item["version"] = int(item.get("version") or 1) + 1
    db.execute("INSERT OR IGNORE INTO property_aliases(entity, alias, property_id) VALUES(?, ?, ?)",
               (item["entity"], clean, property_id))
    db.execute("UPDATE properties SET data = ? WHERE property_id = ?",
               (json.dumps(item, sort_keys=True, ensure_ascii=False), property_id))
    return item


def for_entity(db, entity: str, limit: int = 200) -> list[dict]:
    return [_row(row) for row in
            db.execute("SELECT data FROM properties WHERE entity = ? ORDER BY property_id LIMIT ?",
                       (normalize(entity, field="entity"), limit))]


__all__ = ["resolve", "get", "for_entity", "add_alias", "infer_kind", "EPISODIC"]
