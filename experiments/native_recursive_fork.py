"""Explicitly sealed nested native ancestry; physical files remain distinct.

Observed current semantics: logical ordinal = inherited ordinal + local physical
record count. Only externally known parent paths can be sealed; child metadata
does not authorize filesystem discovery. Maximum ancestry depth is bounded.
"""
from hashlib import sha256
from pathlib import Path

from native_evidence import FIELDS, digest, save, state
from native_rollout_snapshot import parse_rollout
from native_turn_accounting import vector


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def metadata(rows):
    metas = [r['payload'] for r in rows if r['type'] == 'session_meta']
    require(len(metas) == 1, 'recursive_fork_metadata_ambiguous')
    return metas[0]


def seal(child_raw, parent_paths, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    rows = parse_rollout(child_raw).rows
    meta = metadata(rows)
    sealed, seen = [], {meta['id']}
    while meta.get('history_base'):
        require(len(sealed) < 8, 'recursive_fork_depth_exceeded')
        base = meta['history_base']
        tid = base['thread_id']
        require(tid in parent_paths and tid not in seen, 'recursive_fork_parent_unregistered_or_cycle')
        seen.add(tid)
        raw = Path(parent_paths[tid]).read_bytes()
        end = base['end_byte_offset']
        require(type(end) is int and 0 < end <= len(raw), 'recursive_fork_prefix_invalid')
        prefix = raw[:end]
        snap = parse_rollout(prefix)
        require(snap.metadata['parse_complete'] and prefix.endswith(b'\n'), 'recursive_fork_prefix_incomplete')
        pmeta = metadata(snap.rows)
        inherited = (pmeta.get('history_base') or {}).get('end_ordinal_exclusive', 0)
        require(pmeta['id'] == tid and inherited + len(snap.rows) == base['end_ordinal_exclusive'],
                'recursive_fork_logical_ordinal_mismatch')
        require(meta.get('forked_from_id') == tid and meta.get('forked_from_ordinal_exclusive') == base['end_ordinal_exclusive'],
                'recursive_fork_parent_identity_mismatch')
        path = destination / f'{len(sealed):02d}.jsonl'
        with path.open('xb') as stream:
            stream.write(prefix)
        sealed.append(dict(**base, path=str(path), prefix_sha256=sha256(prefix).hexdigest()))
        meta = pmeta
    binding = dict(child_sha256=sha256(child_raw).hexdigest(), child_byte_length=len(child_raw), parents=sealed)
    save(destination / 'binding.json', binding)
    observe(child_raw, binding)
    return binding


def observe(child_raw, binding, *, allow_local_append=False):
    snapshot = parse_rollout(child_raw)
    require(snapshot.metadata['parse_complete'], 'recursive_fork_child_incomplete')
    if not allow_local_append:
        require(snapshot.metadata['sha256'] == binding['child_sha256'], 'recursive_fork_child_changed')
    else:
        require(len(child_raw) >= binding['child_byte_length'] and
                sha256(child_raw[:binding['child_byte_length']]).hexdigest() == binding['child_sha256'],
                'recursive_fork_child_prefix_changed')
    child = snapshot.rows
    meta = metadata(child)
    inherited, seen = [], {meta['id']}
    require(len(binding['parents']) <= 8, 'recursive_fork_depth_exceeded')
    for parent in binding['parents']:
        base = meta.get('history_base')
        require(base == {key: parent[key] for key in ('thread_id', 'end_ordinal_exclusive', 'end_byte_offset')},
                'recursive_fork_base_changed')
        require(base['thread_id'] not in seen, 'recursive_fork_cycle')
        seen.add(base['thread_id'])
        raw = Path(parent['path']).read_bytes()
        require(sha256(raw).hexdigest() == parent['prefix_sha256'] and len(raw) == parent['end_byte_offset'],
                'recursive_fork_parent_seal_changed')
        parsed = parse_rollout(raw)
        require(parsed.metadata['parse_complete'], 'recursive_fork_parent_incomplete')
        pmeta = metadata(parsed.rows)
        ordinal = (pmeta.get('history_base') or {}).get('end_ordinal_exclusive', 0) + len(parsed.rows)
        require(pmeta['id'] == base['thread_id'] and ordinal == base['end_ordinal_exclusive'],
                'recursive_fork_logical_ordinal_mismatch')
        require(meta.get('forked_from_id') == base['thread_id']
                and meta.get('forked_from_ordinal_exclusive') == ordinal, 'recursive_fork_parent_identity_mismatch')
        inherited.insert(0, parsed.rows)
        meta = pmeta
    require(not meta.get('history_base'), 'recursive_fork_ancestry_not_closed')
    inherited_rows = [row for prefix in inherited for row in prefix]
    paid = [r['payload'] for r in inherited_rows if r['type'] == 'token_usage_record']
    counts = [r['payload'].get('info') for r in inherited_rows if r['type'] == 'event_msg'
              and r['payload'].get('type') == 'token_count']
    zero = dict.fromkeys(FIELDS, 0)
    thread = paid[-1]['thread_token_usage'] if paid else zero
    display = (counts[-1] or {}).get('total_token_usage') if counts else zero
    require(vector(thread) and vector(display), 'recursive_fork_counters_unknown')
    require(bool(paid) or (thread == zero and display == zero), 'recursive_fork_unreceipted_inherited_cost')
    ids = [p.get('response_id') for p in paid]
    require(all(isinstance(k, str) and k for k in ids) and len(ids) == len(set(ids)),
            'recursive_fork_inherited_receipts_ambiguous')
    return dict(items=state([*inherited_rows, *child]), inherited_rows=inherited_rows, local_rows=child,
                inherited=dict(thread=thread, display=display, response_ids=ids),
                evidence=dict(depth=len(binding['parents']), child_sha256=snapshot.metadata['sha256'],
                              inherited_records=len(inherited_rows), effective_items_sha256=digest(state([*inherited_rows, *child]))))
