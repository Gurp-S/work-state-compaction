"""Identity census for a CSM namespace: the write-path numbers the diagnosis turns on.

Usage:
    python benchmarks/csm_census.py benchmarks/results/<run>/csm-P01.db [...]
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from pathlib import Path


def _table(db, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (name,)).fetchone() is not None


def census(path: Path) -> dict:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    identities = [json.loads(row["data"]) for row in db.execute("SELECT data FROM identities")]
    live = [item for item in identities if not item.get("merged_into")]
    slots = collections.Counter((item["entity"], item["slot"]) for item in live)
    kinds = collections.Counter(item.get("property_kind") or "unbound" for item in live)
    scopes = collections.Counter((item.get("scope") or "entity").split(":")[0] for item in live)
    revisions = {}
    for row in db.execute("SELECT memory_id, COUNT(*) AS n FROM revisions GROUP BY memory_id"):
        revisions[row["memory_id"]] = row["n"]
    heads = {}
    for row in db.execute("SELECT h.memory_id, r.data FROM heads h JOIN revisions r "
                          "ON r.memory_id = h.memory_id AND r.revision = h.current_revision"):
        heads[row["memory_id"]] = json.loads(row["data"])
    multi = {memory_id: count for memory_id, count in revisions.items() if count > 1}
    by_kind = {}
    for kind in ("state", "event", "unbound"):
        ids = [item["memory_id"] for item in live if (item.get("property_kind") or "unbound") == kind]
        by_kind[kind] = {"identities": len(ids),
                         "multiple_revisions": sum(1 for memory_id in ids if memory_id in multi),
                         "revisions": sum(revisions.get(memory_id, 0) for memory_id in ids)}
    over = sorted(((revisions.get(item["memory_id"], 0), item["entity"], item["slot"],
                    item["memory_id"]) for item in live
                   if revisions.get(item["memory_id"], 0) > 9), reverse=True)
    with_evidence = 0
    for memory_id in (item["memory_id"] for item in live):
        head = heads.get(memory_id)
        if head and head.get("source_refs"):
            with_evidence += 1
    events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    result = {
        "db": str(path),
        "events": events,
        "live_identities": len(live),
        "identities_per_event": round(len(live) / events, 3) if events else None,
        "slots": len(slots),
        "singleton_slots": sum(1 for value in slots.values() if value == 1),
        "singleton_slot_ratio": (round(sum(1 for value in slots.values() if value == 1)
                                       / len(slots), 3) if slots else None),
        "revisions": sum(revisions.values()),
        "revisions_per_identity": (round(sum(revisions.values()) / len(live), 3)
                                   if live else None),
        "identities_with_multiple_revisions": len(multi),
        "identities_with_evidence": with_evidence,
        "empty_context_identities": sum(1 for item in live if not item.get("contexts")),
        "kinds": dict(kinds),
        "kind_detail": by_kind,
        "scopes": dict(scopes),
        "most_revised": [{"revisions": count, "entity": entity, "slot": slot,
                          "head_value": str((heads.get(memory_id) or {}).get("value"))[:80]}
                         for count, entity, slot, memory_id in over[:12]],
    }
    if _table(db, "pending"):
        pending = [json.loads(row["data"]) for row in db.execute(
            "SELECT data FROM pending WHERE status = 'pending'")]
        result["pending"] = len(pending)
        result["pending_by_reason"] = dict(collections.Counter(
            item.get("reason") for item in pending).most_common())
    if _table(db, "relations"):
        result["relations"] = db.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    if _table(db, "tree_mounts"):
        result["tree_mounts"] = db.execute("SELECT COUNT(*) FROM tree_mounts").fetchone()[0]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("databases", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    report = [census(path) for path in args.databases]
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
