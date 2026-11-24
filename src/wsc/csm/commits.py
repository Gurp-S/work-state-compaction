"""Commit anchors: an ingested commit event fixes the instant an as-of query resolves to.

A commit is not a scope and not a revision; it is the event-time key a coding caller uses
instead of a wall-clock instant. Unknown commits are refused rather than interpolated.
"""
from __future__ import annotations

import json

from .contracts import require


def key(metadata: dict | None) -> str | None:
    """The commit identity a source event declares, if any."""
    if not isinstance(metadata, dict):
        return None
    for name in ("commit", "sha"):
        value = metadata.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def register(db, sha: str, observed_at: str, data: dict) -> bool:
    """First observation of a commit wins: history is immutable, re-ingest is idempotent."""
    if not sha or not observed_at:
        return False
    cursor = db.execute(
        "INSERT INTO commits(commit_sha, observed_at, data) VALUES(?, ?, ?) "
        "ON CONFLICT(commit_sha) DO NOTHING",
        (sha, observed_at, json.dumps(data, sort_keys=True, ensure_ascii=False)))
    return bool(cursor.rowcount)


def get(db, sha: str) -> dict | None:
    row = db.execute("SELECT commit_sha, observed_at, data FROM commits WHERE commit_sha = ?",
                     (sha,)).fetchone()
    if row is None:
        return None
    return {"commit": row["commit_sha"], "observed_at": row["observed_at"],
            "data": json.loads(row["data"])}


def instant(db, sha: str) -> str:
    row = db.execute("SELECT observed_at FROM commits WHERE commit_sha = ?", (sha,)).fetchone()
    require(row is not None and bool(row["observed_at"]), "commit_unknown")
    return row["observed_at"]


__all__ = ["key", "register", "get", "instant"]
