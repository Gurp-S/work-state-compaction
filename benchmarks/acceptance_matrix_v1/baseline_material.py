"""Empty history is a verified no-op, never an empty native injection."""
from pathlib import Path
from native_blackbox_sessions import import_fresh,verify_material
from native_rollout_snapshot import capture_rollout
from native_evidence import state


def import_baseline(session,prefix,bootstrap,folder):
    if prefix:return import_fresh(session,prefix,bootstrap,folder)
    snapshot=capture_rollout(session.opened['thread']['path'])
    if not snapshot.metadata['parse_complete'] or any(row.get('type')=='token_usage_record' for row in snapshot.rows):
        raise ValueError('empty_history_unverifiable_or_inference_observed')
    proof=verify_material(state(snapshot.rows),bootstrap,[],workspace=session.registration['workspace'])
    from .paired_cell import save
    save(Path(folder)/'empty-history-proof.json',dict(proof=proof,no_injection_call=True,snapshot=snapshot.metadata))
    return proof
