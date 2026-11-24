"""Event groups (§3.3): one semantic event may need several atomic memories.

A group is a commit unit, not a batch convenience. Members that can be decided commit in
one transaction; members that cannot are parked as pending; the group records exactly
which half happened. Re-submitting a group that already committed is idempotent.
"""
from __future__ import annotations

import json

from ..contracts import require


def get(db, group_id: str) -> dict | None:
    row = db.execute("SELECT data FROM event_groups WHERE group_id = ?", (group_id,)).fetchone()
    return None if row is None else json.loads(row["data"])


def record(db, group_id: str, *, members, deferred, status: str, recorded_at: str) -> dict:
    """Store the group outcome once. A committed group is never rewritten."""
    require(isinstance(group_id, str) and bool(group_id.strip()), "event_group_invalid")
    require(status in ("committed", "partial", "deferred"), "event_group_status_invalid")
    existing = get(db, group_id)
    if existing is not None:
        require(existing["status"] == "committed" or existing["status"] == status,
                "event_group_conflict")
        return {**existing, "changed": False}
    data = {"group_id": group_id, "status": status, "members": list(members),
            "deferred": list(deferred), "recorded_at": recorded_at}
    db.execute("INSERT INTO event_groups(group_id, status, data, recorded_at) "
               "VALUES(?, ?, ?, ?)",
               (group_id, status, json.dumps(data, sort_keys=True, ensure_ascii=False),
                recorded_at))
    return {**data, "changed": True}


def listing(db, *, limit: int = 100, status: str | None = None) -> list[dict]:
    if status is None:
        rows = db.execute("SELECT data FROM event_groups ORDER BY recorded_at DESC, group_id "
                          "LIMIT ?", (limit,))
    else:
        rows = db.execute("SELECT data FROM event_groups WHERE status = ? "
                          "ORDER BY recorded_at DESC, group_id LIMIT ?", (status, limit))
    return [json.loads(row["data"]) for row in rows]


__all__ = ["get", "record", "listing"]
