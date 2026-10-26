"""Observe a registered native fork's parent prefix without rewriting history.

JSONL parse_complete describes a physical file, not materialized paginated
history. This opt-in reader resolves one externally registered, standalone
parent. Nested bases are rejected until their ordinal semantics are verified.
No encrypted content is interpreted and no model request equality is asserted.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from native_evidence import state, digest
from native_rollout_snapshot import parse_rollout
from native_task_checks import require


def _meta(snapshot):
    require(snapshot.metadata['parse_complete'], 'fork_history_file_incomplete')
    records = [r['payload'] for r in snapshot.rows if r['type'] == 'session_meta']
    require(len(records) == 1, 'fork_history_metadata_ambiguous')
    return records[0]


def observe_registered_fork(child_path, binding):
    """binding pins child bytes plus parent identity, offsets and prefix bytes.

    Parent suffix appends do not invalidate the inherited prefix. A caller must
    register the binding from a trusted source observation; references inside
    the child file alone do not establish that binding.
    """
    return observe_fork_bytes(Path(child_path).read_bytes(), binding)


def observe_fork_bytes(child_raw, binding):
    """Resolve an already-captured child observation without a second child read."""
    require(sha256(child_raw).hexdigest() == binding['child_sha256'], 'fork_history_child_changed')
    child = parse_rollout(child_raw)
    meta = _meta(child)
    parent = binding['parent']
    expected = {k: parent[k] for k in ('thread_id', 'end_ordinal_exclusive', 'end_byte_offset')}
    require(meta.get('history_mode') == 'paginated' and meta.get('history_base') == expected,
            'fork_history_base_mismatch')
    require(meta.get('id') != parent['thread_id'] and meta.get('forked_from_id') == parent['thread_id']
            and meta.get('forked_from_ordinal_exclusive') == parent['end_ordinal_exclusive'],
            'fork_history_parent_identity_mismatch')
    end, ordinal = parent['end_byte_offset'], parent['end_ordinal_exclusive']
    require(type(end) is int and end > 0 and type(ordinal) is int and ordinal > 0,
            'fork_history_boundary_invalid')
    # One read for the parent, before slicing, prevents cross-read hash/parse drift.
    parent_raw = Path(parent['path']).read_bytes()
    require(end <= len(parent_raw), 'fork_history_prefix_truncated')
    prefix = parent_raw[:end]
    require(prefix.endswith(b'\n'), 'fork_history_boundary_not_record_end')
    require(sha256(prefix).hexdigest() == parent['prefix_sha256'], 'fork_history_parent_prefix_changed')
    inherited = parse_rollout(prefix)
    inherited_meta = _meta(inherited)
    require(inherited_meta.get('id') == parent['thread_id'], 'fork_history_registered_parent_mismatch')
    require(not inherited_meta.get('history_base'), 'fork_history_nested_parent_unresolved')
    require(len(inherited.rows) == ordinal, 'fork_history_ordinal_mismatch')
    # Keep original rows separate. Combining them as a purported native rollout
    # would create two session_meta rows and invent a new observation identity.
    effective = [*inherited.rows, *child.rows]
    compacted = [r['payload'] for r in effective if r['type'] == 'compacted']
    items = state(effective)
    return {'items': deepcopy(items), 'latest_compaction': deepcopy(compacted[-1]) if compacted else None,
            'inherited_rows': deepcopy(inherited.rows), 'local_rows': deepcopy(child.rows),
            'evidence': {'child_sha256': child.metadata['sha256'], 'parent_prefix_sha256': inherited.metadata['sha256'],
                'parent_thread_id': parent['thread_id'], 'end_byte_offset': end, 'end_ordinal_exclusive': ordinal,
                'effective_items_sha256': digest(items), 'local_records': len(child.rows),
                'inherited_records': len(inherited.rows),
                'scope': 'Registered standalone parent prefix plus fork-local records; not a cross-file atomic snapshot or submitted-model-request proof'}}
