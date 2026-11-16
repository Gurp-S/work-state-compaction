"""A persisted, incrementally maintained embedding index: one row per live memory.

Rebuilding every vector on every query is the reason the vector path could not be trusted
under load, and the reason a superseded value kept surfacing. The index keeps each row's
revision and a content fingerprint, so a query embeds only what actually changed and can
filter candidates before it ranks them.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from . import filters
from . import identity as identities
from . import state
from .contracts import require
from .recall_cache import content_signature, database_key, embedder_key


def fingerprint(identity: dict, record: dict, topics: list[str]) -> str:
    """Content hash of exactly the text that gets embedded."""
    payload = json.dumps([identity["entity"], identity["slot"], identity["contexts"],
                          record.get("value"), list(topics)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(identity: dict, record: dict, topics: list[str]) -> str:
    return " ".join((identity["entity"], identity["slot"], str(record.get("value") or ""),
                     " ".join(topics)))


def _blob(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


class Index:
    """Maintains ``vector_index``: embed what changed, forget what is gone."""

    def __init__(self, db, embedder):
        self.db = db
        self.embedder = embedder

    def _live(self) -> list[dict]:
        rows = []
        for row in self.db.execute("SELECT memory_id, data FROM identities ORDER BY memory_id"):
            identity = json.loads(row["data"])
            if identity.get("merged_into"):
                continue
            record = state.head(self.db, row["memory_id"])
            if record is None:
                continue
            topics = identities.topics_of(self.db, row["memory_id"])
            rows.append({"identity": identity, "record": record, "topics": topics,
                         "text": _text(identity, record, topics),
                         "fingerprint": fingerprint(identity, record, topics)})
        return rows

    def sync(self, *, recorded_at: str = "", live=None) -> dict:
        live = self._live() if live is None else live
        for item in live:
            item["fingerprint"] = hashlib.sha256(json.dumps(
                [item["fingerprint"], embedder_key(self.embedder)],
                sort_keys=True).encode("utf-8")).hexdigest()
        stored = {row["memory_id"]: row for row in self.db.execute(
            "SELECT memory_id, revision, fingerprint, dim FROM vector_index")}
        missing = [item for item in live
                   if item["identity"]["memory_id"] not in stored
                   or stored[item["identity"]["memory_id"]]["fingerprint"] != item["fingerprint"]
                   or stored[item["identity"]["memory_id"]]["revision"] != item["record"]["revision"]]
        gone = [memory_id for memory_id in stored
                if memory_id not in {item["identity"]["memory_id"] for item in live}]
        embedded = 0
        if missing:
            vectors = self.embedder.embed([item["text"] for item in missing])
            for item, vector in zip(missing, vectors):
                vector = np.asarray(vector, dtype=np.float32)
                self.db.execute(
                    "INSERT INTO vector_index(memory_id, revision, fingerprint, dim, vector, "
                    "updated_at) VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(memory_id) DO UPDATE SET "
                    "revision = excluded.revision, fingerprint = excluded.fingerprint, "
                    "dim = excluded.dim, vector = excluded.vector, updated_at = excluded.updated_at",
                    (item["identity"]["memory_id"], item["record"]["revision"],
                     item["fingerprint"], int(vector.shape[0]), _blob(vector), recorded_at))
                embedded += 1
        for memory_id in gone:
            self.db.execute("DELETE FROM vector_index WHERE memory_id = ?", (memory_id,))
        return {"embedded": embedded, "reused": len(live) - embedded, "removed": len(gone),
                "total": len(live)}

    def load(self) -> tuple[list[dict], np.ndarray]:
        """Rows and matrix in one order; the caller never re-embeds to read them."""
        data = self.db.execute("SELECT memory_id, dim, vector FROM vector_index "
                               "ORDER BY memory_id").fetchall()
        if not data:
            return [], np.zeros((0, 1), dtype=np.float32)
        rows = self._live()
        by_id = {item["identity"]["memory_id"]: item for item in rows}
        kept, vectors = [], []
        for row in data:
            item = by_id.get(row["memory_id"])
            if item is None:
                continue
            kept.append(item)
            vectors.append(np.frombuffer(row["vector"], dtype=np.float32)[:row["dim"]])
        if not vectors:
            return [], np.zeros((0, 1), dtype=np.float32)
        return kept, np.vstack(vectors)


_CACHE: dict[tuple, tuple] = {}


def search(db, text: str, limit: int = 20, *, embedder=None, entities=None, contexts=None,
           lifecycle=None, status=None, window=None, diverse: bool = False) -> dict:
    """Cosine ranking over candidates that already passed the hard filters."""
    from . import diversity as diversify
    from . import vector

    embedder = embedder or vector._embedder()
    index = Index(db, embedder)
    key = database_key(db)
    rows = index._live()
    live = content_signature(rows, embedder)
    cached = _CACHE.get(key)
    if cached is None or cached[0] != live:
        index.sync(live=rows)
        rows, matrix = index.load()
        _CACHE[key] = (live, rows, matrix)
    else:
        _, rows, matrix = cached
    if not rows:
        return {"query": {"text": text}, "results": [], "counts": {}, "index": {"total": 0}}
    if hasattr(embedder, "query"):
        query_vector = embedder.query(text)[0]
    else:
        query_vector = embedder.embed([text])[0]
    anchor_of = {id(item): {"entity": item["identity"]["entity"],
                            "contexts": item["identity"]["contexts"],
                            "lifecycle": item["record"].get("lifecycle"),
                            "status": item["record"].get("status"),
                            "effective_at": item["record"].get("effective_at"),
                            "valid_from": item["record"].get("valid_from")}
                 for item in rows}
    candidates, dropped = [], {}
    for item in rows:
        ok, reason = filters.keep(anchor_of[id(item)], entities=entities, contexts=contexts,
                                  lifecycle=lifecycle, status=status, window=window)
        if ok:
            candidates.append(item)
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    if not candidates:
        return {"query": {"text": text}, "results": [], "counts": {}, "filtered": dropped}
    from . import retrieval

    at = {id(item): index for index, item in enumerate(rows)}
    positions = [at[id(item)] for item in candidates]
    scores = matrix[positions] @ np.asarray(query_vector, dtype=np.float32)
    order = sorted(range(len(scores)),
                   key=lambda slot: (-float(scores[slot]), candidates[slot]["identity"]["memory_id"]))
    results = []
    for slot in order:
        score = float(scores[slot])
        if score <= 0:
            continue
        candidate = candidates[int(slot)]
        classification, reason = filters.classify(
            candidate["record"], candidate["record"]["revision"],
            lifecycle=candidate["record"].get("lifecycle"))
        item = retrieval._view(db, candidate["identity"], candidate["record"])
        item.update({"classification": classification,
                     "confirmed": classification == "CURRENT_CONFIRMED",
                     "reason": reason, "score": round(score, 4),
                     "uncertainty": {"classification": classification,
                                     "confirmed": classification == "CURRENT_CONFIRMED",
                                     "missing_conditions": []}})
        results.append(item)
        if len(results) >= max(limit * 4, limit):
            break
    if diverse and len(results) > limit:
        results = diversify.mmr(results, limit, text_of=lambda row: row.get("value"),
                                score_of=lambda row: row["score"])
    results = results[:limit]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return {"query": {"text": text}, "results": results, "counts": counts, "filtered": dropped}


__all__ = ["fingerprint", "Index", "search"]
