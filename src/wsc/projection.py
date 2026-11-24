"""Pure public-material and checkpoint-binding projections; no source authority."""
from . import state_view


def snapshot_binding(snapshot, *, understanding_epoch):
    # Snapshot's public history fields remain available to callers. A binding
    # contains only identity/version scalars and never needs to copy that history.
    return {"session_id": snapshot.session_id, "workspace": snapshot.workspace,
            "generation": snapshot.generation, "control_epoch": snapshot.control_epoch,
            "understanding_epoch": understanding_epoch, "cut": snapshot.cut,
            "source_digest": snapshot.source_digest}


def public_material(prefix, records):
    # H1: the ledger's current entries lead the material; raw events follow as
    # their evidence. Superseded or expired revisions are history, not material.
    source_ids = {row["id"] for row in prefix}
    current = [record for record in state_view.current_entries(records, prefix)
               if set(record["sources"]) <= source_ids]
    return {"understandings": current,
            "events": [{key: row[key] for key in
                       ("id", "seq", "kind", "role", "call_id", "text", "observed_at")}
                      for row in prefix if row["kind"] != "opaque"]}
