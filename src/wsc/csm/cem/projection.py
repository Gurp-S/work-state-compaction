"""Projection rebuild: the index may be recomputed, the facts may not change."""
from __future__ import annotations

import json

from .. import identity as identities
from .. import state


def rebuild(db) -> dict:
    """Recompute every current-state projection from committed revisions.

    Repairs only what is provably recoverable (a head pointing past its last
    revision, a stale or missing projection row) and reports anything else.
    """
    report = {"memories": 0, "rewritten": [], "repaired_heads": [], "dropped_orphans": [],
              "damaged": []}
    rows = db.execute("SELECT memory_id, current_revision FROM heads ORDER BY memory_id").fetchall()
    for row in rows:
        memory_id = row["memory_id"]
        try:
            identity = identities.identity_row(db, memory_id)
        except Exception:
            report["damaged"].append({"memory_id": memory_id, "reason": "identity_missing"})
            continue
        available = [item["revision"] for item in state.revisions(db, memory_id)]
        if not available:
            report["damaged"].append({"memory_id": memory_id, "reason": "revision_missing"})
            continue
        number = row["current_revision"]
        if number not in available:
            number = max(available)
            db.execute("UPDATE heads SET current_revision = ?, projection_version = ? "
                       "WHERE memory_id = ?", (number, number, memory_id))
            report["repaired_heads"].append({"memory_id": memory_id, "revision": number})
        current = state.revision(db, memory_id, number)
        payload = state.projection_payload(identity, current, identities.topics_of(db, memory_id))
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        stored = db.execute("SELECT data FROM projection WHERE memory_id = ?",
                            (memory_id,)).fetchone()
        if stored is None or stored["data"] != text:
            db.execute("INSERT INTO projection(memory_id, data) VALUES(?, ?) "
                       "ON CONFLICT(memory_id) DO UPDATE SET data = excluded.data",
                       (memory_id, text))
            report["rewritten"].append(memory_id)
        report["memories"] += 1
    orphans = [row["memory_id"] for row in
               db.execute("SELECT memory_id FROM projection ORDER BY memory_id")
               if db.execute("SELECT 1 FROM heads WHERE memory_id = ?",
                             (row["memory_id"],)).fetchone() is None]
    for memory_id in orphans:
        db.execute("DELETE FROM projection WHERE memory_id = ?", (memory_id,))
    report["dropped_orphans"] = orphans
    return report
