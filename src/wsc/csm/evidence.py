"""Source evidence for retrieval results: the memory row is an index, the event is the fact.

A projected value answers "what does the engine believe"; it does not answer "what was
actually said". The answer model needs the latter, so top results carry a bounded excerpt
of the source event they were extracted from.
"""
from __future__ import annotations

import json

DEFAULT_CHARS = 700


def _text(payload) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        parts = []
        for key in ("user", "assistant", "text", "content", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        if parts:
            return "\n".join(parts)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def fetch(db, source_ids, *, max_chars: int = DEFAULT_CHARS) -> list[dict]:
    """One batched lookup for all evidence of the selected rows."""
    ids = [item for item in dict.fromkeys(source_ids or []) if item]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = {row["id"]: row for row in db.execute(
        f"SELECT id, observed_at, data FROM events WHERE id IN ({marks})", ids)}
    out = []
    for source_id in ids:
        row = rows.get(source_id)
        if row is None:
            continue
        text = _text(json.loads(row["data"]))
        out.append({"source_id": source_id, "observed_at": row["observed_at"],
                    "text": text[:max_chars]})
    return out


def attach(db, results: list[dict], *, max_chars: int = DEFAULT_CHARS) -> list[dict]:
    """Attach evidence to each result in one query; empty when the source was not ingested."""
    wanted = []
    for item in results:
        wanted.extend(item.get("source_refs") or [])
    packet = {entry["source_id"]: entry for entry in fetch(db, wanted, max_chars=max_chars)}
    for item in results:
        item["evidence"] = [packet[source] for source in item.get("source_refs") or []
                            if source in packet]
    return results


__all__ = ["fetch", "attach", "DEFAULT_CHARS"]
