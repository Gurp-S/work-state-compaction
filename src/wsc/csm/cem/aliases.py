"""Alias resolution: which surface names denote one entity, and on what evidence.

"小许" and "许澄" are the same person only when something says so. Detection is therefore
evidence-gated — a marker in an ingested event, an identical value under the same slot, or
a surface variant of the same name — and confirmation is recorded, never inferred from
similarity alone. Retrieval expands a query name through confirmed aliases so a memory
written under one name is reachable under the other.
"""
from __future__ import annotations

import json
import re

from ..contracts import require

_MARKER = re.compile(
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,19})"
    r"\s*[（(]\s*(?:又名|也叫|也叫作|小名|昵称|别称|alias)\s*[:：]?\s*"
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,19})\s*[)）]")
_ALSO = re.compile(
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,19})\s*"
    r"(?:，|,|、)?\s*(?:又名|也叫|也叫作|小名|昵称|别称|aka)\s*[:：]?\s*"
    r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z·]{0,19})")
_CONFIDENCE = {"explicit_marker": 0.95, "value_match": 0.6, "surface_variant": 0.4}


def _live(db) -> list[dict]:
    return [json.loads(row["data"]) for row in
            db.execute("SELECT data FROM identities ORDER BY memory_id")
            if not json.loads(row["data"]).get("merged_into")]


def links(db, entity: str) -> list[str]:
    """Confirmed names equivalent to ``entity``, in either direction, deduplicated."""
    names = {entity}
    for row in db.execute("SELECT alias, entity FROM entity_aliases WHERE status = 'confirmed'"):
        if row["alias"] == entity:
            names.add(row["entity"])
        if row["entity"] == entity:
            names.add(row["alias"])
    return sorted(names)


def canonical(db, entity: str) -> str:
    """The name a write should land under.

    Preferring the shortest name picked a name no identity used yet, which forked the history
    instead of joining it, so an existing identity's entity wins; length and name only break
    ties among equals.
    """
    names = links(db, entity)
    known = {row[0] for row in db.execute("SELECT DISTINCT entity FROM identities")}
    pool = [name for name in names if name in known] or names
    return sorted(pool, key=lambda name: (len(name), name))[0]


def _evidence(db, source_ids) -> list[str]:
    ids = [item for item in source_ids if item]
    require(ids, "alias_evidence_missing")
    marks = ",".join("?" * len(ids))
    found = {row["id"] for row in db.execute(f"SELECT id FROM events WHERE id IN ({marks})", ids)}
    require(all(item in found for item in ids), "evidence_source_unknown")
    return ids


def confirm(db, alias: str, entity: str, evidence, *, kind: str = "explicit_marker",
            confidence: float | None = None, recorded_at: str) -> dict:
    """Record that ``alias`` names ``entity``. Evidence is required; similarity is not it."""
    require(alias and entity and alias != entity, "alias_invalid")
    ids = _evidence(db, evidence)
    value = _CONFIDENCE.get(kind, 0.5) if confidence is None else float(confidence)
    db.execute("INSERT INTO entity_aliases(alias, entity, status, confidence, evidence, "
               "created_at) VALUES(?, ?, 'confirmed', ?, ?, ?) "
               "ON CONFLICT(alias, entity) DO UPDATE SET status = 'confirmed', "
               "confidence = excluded.confidence, evidence = excluded.evidence",
               (alias, entity, value, json.dumps(ids, ensure_ascii=False), recorded_at))
    return {"alias": alias, "entity": entity, "kind": kind, "confidence": value,
            "evidence": ids, "names": links(db, entity)}


def proposals(db) -> list[dict]:
    """Unconfirmed alias candidates with the evidence that suggests them. Nothing is written."""
    out = []
    known = {(row["alias"], row["entity"]) for row in
             db.execute("SELECT alias, entity FROM entity_aliases WHERE status = 'confirmed'")}
    live = _live(db)
    for identity in live:
        for source_id in identity.get("identity_evidence") or []:
            row = db.execute("SELECT data FROM events WHERE id = ?", (source_id,)).fetchone()
            if row is None:
                continue
            text = json.dumps(json.loads(row["data"]), ensure_ascii=False)
            for pattern in (_MARKER, _ALSO):
                for match in pattern.finditer(text):
                    left, right = match.group(1).strip(), match.group(2).strip()
                    if left == right:
                        continue
                    for alias, entity in ((left, right), (right, left)):
                        if (alias, entity) in known:
                            continue
                        out.append({"alias": alias, "entity": entity,
                                    "kind": "explicit_marker", "evidence": [source_id],
                                    "confidence": _CONFIDENCE["explicit_marker"]})
    by_slot: dict[tuple, list[dict]] = {}
    for identity in live:
        by_slot.setdefault((identity["slot"], json.dumps(identity["contexts"])), []).append(identity)
    for group in by_slot.values():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                if left["entity"] == right["entity"]:
                    continue
                pair = (left["entity"], right["entity"])
                if pair in known:
                    continue
                short, long = sorted((left["entity"], right["entity"]), key=len)
                if long.startswith(short) or long.endswith(short):
                    if len(long) - len(short) <= 3:
                        out.append({"alias": short, "entity": long, "kind": "surface_variant",
                                    "evidence": [], "confidence": _CONFIDENCE["surface_variant"]})
    return out


__all__ = ["links", "canonical", "confirm", "proposals"]
