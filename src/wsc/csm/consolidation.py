"""Consolidation replaces the write-time pending pool.

A write never parks a fact because identity is unclear: a state property updates, an event
property appends under its own event scope, and the engine's property registry makes the
binding stable. Consolidation is the maintenance pass that audits that invariant and
backfills property records for stores written by the old string-key model.
"""
from __future__ import annotations

import json

from . import properties


def run(db, *, recorded_at: str = "") -> dict:
    """Audit identities and backfill property records; no revision is rewritten."""
    stats = {"identities": 0, "backfilled": 0, "state": 0, "event": 0, "unbound": 0}
    rows = db.execute("SELECT memory_id, data FROM identities ORDER BY memory_id").fetchall()
    for row in rows:
        data = json.loads(row["data"])
        if data.get("merged_into"):
            continue
        stats["identities"] += 1
        property_id = data.get("property_id")
        if not property_id:
            item = properties.resolve(db, data["entity"], data["slot"],
                                      kind=data.get("property_kind"),
                                      scope=data.get("scope"), recorded_at=recorded_at)
            data["property_id"] = item["property_id"]
            data["property_kind"] = item["kind"]
            data["scope"] = data.get("scope") or item["scope"]
            db.execute("UPDATE identities SET data = ?, property_id = ?, property_kind = ?, "
                       "scope = ? WHERE memory_id = ?",
                       (json.dumps(data, sort_keys=True, ensure_ascii=False),
                        data["property_id"], data["property_kind"], data["scope"],
                        row["memory_id"]))
            stats["backfilled"] += 1
            property_id = item["property_id"]
        item = properties.get(db, property_id)
        if item is None:
            stats["unbound"] += 1
        elif item["kind"] == "event":
            stats["event"] += 1
        else:
            stats["state"] += 1
    return stats


__all__ = ["run"]
