"""Current-state projection: which ledger entries are still applicable at a cut.

Validity is mechanical, driven by the entry's own source pointers: a
file_changed condition fires on any write/edit call to that path whose event
seq is newer than the newest source the entry cites. An entry citing no source
is conservatively invalidated by any matching call in the prefix. valid_until
is compared against the newest observation time in the prefix, never a wall
clock.
"""
import json

from .contracts import require
from .understanding import STATE_FIELDS

INVALID_WHEN_KEYS = ("file_changed",)
_EDIT_NAMES = ("write", "edit")


def latest_observed_at(prefix) -> str | None:
    times = [row["observed_at"] for row in prefix if row.get("observed_at")]
    return max(times) if times else None


def _call_path(row) -> str | None:
    payload = row.get("payload") or {}
    if payload.get("name") not in _EDIT_NAMES:
        return None
    arguments = payload.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    for key in ("path", "file_path", "target_file", "notebook_path"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _entry_seq(entry, by_id) -> int:
    seqs = [by_id[key]["seq"] for key in entry["sources"] if key in by_id]
    return max(seqs) if seqs else -1


def entry_expired(entry, prefix, now, *, by_id=None) -> bool:
    if entry["status"] != "active":
        return True
    if entry["valid_until"] and now and entry["valid_until"] <= now:
        return True
    conditions = entry["invalid_when"] or {}
    for key in conditions:
        require(key in INVALID_WHEN_KEYS, "unsupported_invalid_when")
    if not conditions:
        return False
    by_id = by_id if by_id is not None else {row["id"]: row for row in prefix}
    anchor = _entry_seq(entry, by_id)
    for row in prefix:
        if row["kind"] != "call" or row["seq"] <= anchor:
            continue
        path = _call_path(row)
        if path is not None and conditions.get("file_changed") == path:
            return True
    return False


def current_entries(records, prefix) -> list[dict]:
    # The ledger's current state is the head revision of each identity; older
    # revisions stay readable as history but are never current facts.
    heads = {}
    for record in records:
        record = {**STATE_FIELDS, **record}
        head = heads.get(record["id"])
        if head is None or record["revision"] > head["revision"]:
            heads[record["id"]] = record
    now = latest_observed_at(prefix)
    by_id = {row["id"]: row for row in prefix}
    return [record for record in heads.values()
            if not entry_expired(record, prefix, now, by_id=by_id)]