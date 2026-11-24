"""Write-side hygiene: suppress restated observations, digest superseded revisions.

Two kinds of bloat cost the reader: a memory that gains a revision every time the same fact
is observed again, and a long history where every superseded value competes with the current
one. The first is prevented (a near-duplicate observation is not a new revision), the second
is folded into a mechanical digest that names each value and when it held — no rewriting of
committed revisions, no model call.
"""
from __future__ import annotations

import json
import re

from . import diversity
from .. import state

_PUNCT = re.compile(r"[\s\u3000,，。.;；:：!！?？\"'“”‘’()（）\[\]【】<>《》-]+")


def normalized(value) -> str:
    return _PUNCT.sub("", str(value or "").lower())


def near_duplicate(left, right, *, threshold: float = 0.85) -> bool:
    """Same fact stated twice: identical after normalization, or near-identical tokens."""
    first, second = normalized(left), normalized(right)
    if not first or not second:
        return False
    if first == second:
        return True
    if first in second or second in first:
        return min(len(first), len(second)) / max(len(first), len(second)) >= 0.6
    return diversity.jaccard(diversity.tokens(first), diversity.tokens(second)) >= threshold


def duplicate_of_head(db, memory_id: str, value) -> dict | None:
    """The head revision when this observation would only restate it, else None."""
    head = state.head(db, memory_id)
    if head is None:
        return None
    return head if near_duplicate(head.get("value"), value) else None


def superseded(db, memory_id: str) -> list[dict]:
    head = state.head(db, memory_id)
    if head is None:
        return []
    return [json.loads(row["data"]) for row in
            db.execute("SELECT data FROM revisions WHERE memory_id = ? AND revision < ? "
                       "ORDER BY revision", (memory_id, head["revision"]))]


def digest_of(db, memory_id: str) -> dict | None:
    row = db.execute("SELECT through_revision, digest, created_at FROM memory_digests "
                     "WHERE memory_id = ?", (memory_id,)).fetchone()
    return None if row is None else {"through_revision": row["through_revision"],
                                     "digest": row["digest"], "created_at": row["created_at"]}


def compact(db, memory_id: str, *, recorded_at: str = "", keep: int = 12) -> dict:
    """Fold superseded revisions into one digest; the revisions themselves stay readable."""
    history = superseded(db, memory_id)
    if not history:
        db.execute("DELETE FROM memory_digests WHERE memory_id = ?", (memory_id,))
        return {"memory_id": memory_id, "digest": None, "folded": 0}
    lines, seen = [], set()
    for record in history:
        key = normalized(record.get("value"))
        if not key or key in seen:
            continue
        seen.add(key)
        when = record.get("effective_at") or record.get("recorded_at") or ""
        lines.append(f"v{record.get('revision')} [{when}] {record.get('value')}")
    digest = "\n".join(lines[-keep:])
    through = history[-1]["revision"]
    db.execute("INSERT INTO memory_digests(memory_id, through_revision, digest, created_at) "
               "VALUES(?, ?, ?, ?) ON CONFLICT(memory_id) DO UPDATE SET "
               "through_revision = excluded.through_revision, digest = excluded.digest, "
               "created_at = excluded.created_at",
               (memory_id, through, digest, recorded_at))
    return {"memory_id": memory_id, "digest": digest, "through_revision": through,
            "folded": len(lines), "omitted": max(0, len(lines) - keep)}


__all__ = ["normalized", "near_duplicate", "duplicate_of_head", "superseded", "digest_of",
           "compact"]
