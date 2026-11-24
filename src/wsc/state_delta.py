"""H3: what changed in the ledger since a previous presentation.

Identity-level delta: an identity whose current revision differs from the one
last presented is revised; an identity absent before is added; a previously
presented identity with no current entry is expired. Refs are identities, never
parsed as paths.
"""
from .state_view import current_entries


def _identity(ref: str) -> str:
    return ref.rsplit("@", 1)[0]


def delta(previous_refs, records, prefix) -> dict:
    current = current_entries(records, prefix)
    current_by_id = {_identity(r["ref"]): r for r in current}
    previous_by_id = {_identity(ref): ref for ref in previous_refs}
    added, revised, expired = [], [], []
    for identity, record in current_by_id.items():
        if identity not in previous_by_id:
            added.append(record["ref"])
        elif previous_by_id[identity] != record["ref"]:
            revised.append({"ref": record["ref"], "previous": previous_by_id[identity]})
    for identity, ref in previous_by_id.items():
        if identity not in current_by_id:
            expired.append(ref)
    return {"added": added, "revised": revised, "expired": expired}