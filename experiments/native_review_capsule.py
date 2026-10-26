"""Exact source-bound review facts; full manifests stay in a cold index."""
from datetime import datetime, timezone
from pathlib import Path

from native_evidence import read, save, file_hash, manifest, digest


def _checks(value):
    result = value.get('outcomes', value.get('checks'))
    if not isinstance(result, list) or not result:
        raise ValueError('review_receipt_checks_missing')
    if value.get('mutation', 'none') != 'none' or value.get('source_unchanged', True) is not True:
        raise ValueError('review_receipt_not_current_unmutated_source')
    return [dict(id=row['id'], passed=row['passed']) for row in result]


def build(gui, groups, destination, *, expected_checks, previous_run):
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    current = manifest(Path(gui) / 'src')
    facts, receipts = [], []
    for group in groups:
        registration, result = Path(group['registration']), Path(group['result'])
        if read(registration)['source_manifest'] != current:
            raise ValueError('review_receipt_source_binding_changed')
        facts.extend(_checks(read(result)))
        for path in (registration, result):
            receipts.append(dict(path=str(path), sha256=file_hash(path)))
    if (len(facts) != len(expected_checks) or len({row['id'] for row in facts}) != len(facts)
            or {row['id'] for row in facts} != set(expected_checks)
            or any(type(row['passed']) is not bool for row in facts)):
        raise ValueError('review_receipt_scope_changed')
    old = read(previous_run)
    receipts.append(dict(path=str(previous_run), sha256=file_hash(previous_run)))
    projection = dict(format='native_review_facts/1', scope='existing_S3_delivery_review_only',
        source_manifest_sha256=digest(current), checks=facts,
        checks_count=len(facts), all_checks_passed=all(row['passed'] for row in facts),
        original_stage_status=old['failure'], original_stage_usage_complete=old.get('usage_complete'),
        BC_benefit_proven=False, development_history_in_capsule=False,
        binding_checked_at=datetime.now(timezone.utc).isoformat())
    index = dict(gui=str(gui), source_manifest=current, receipts=receipts, projection=projection)
    save(destination / 'index.json', index)
    hot = {**projection, 'cold_index': dict(path=str(destination / 'index.json'), sha256=file_hash(destination / 'index.json'))}
    save(destination / 'facts.json', hot)
    verify(hot)
    return hot


def verify(hot):
    locator = hot['cold_index']
    if file_hash(locator['path']) != locator['sha256']:
        raise ValueError('review_capsule_index_changed')
    index = read(locator['path'])
    if {key: value for key, value in hot.items() if key != 'cold_index'} != index['projection']:
        raise ValueError('review_capsule_facts_changed')
    if manifest(Path(index['gui']) / 'src') != index['source_manifest']:
        raise ValueError('review_capsule_source_changed')
    if any(file_hash(row['path']) != row['sha256'] for row in index['receipts']):
        raise ValueError('review_capsule_receipt_changed')
    return index


def open_receiver(registration, destination, hot):
    """Review capsules enter a fresh read-only receiver, never a history fork."""
    from native_application_session import NativeApplicationSession
    from native_evidence import import_evidence
    from native_rollout_snapshot import parse_rollout
    import json
    verify(hot)
    reg = {key: value for key, value in registration.items()
           if key not in ('parent_thread_id', 'parent_paths', 'before_turn_id')}
    reg['sandbox'] = 'read-only'
    session = NativeApplicationSession(reg, destination)
    try:
        session.open()
        path = Path(session.opened['thread']['path'])
        before = path.read_bytes()
        item = dict(type='message', role='developer', content=[dict(type='input_text',
            text=json.dumps(hot, ensure_ascii=False, separators=(',', ':')))])
        session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[item]))
        after = path.read_bytes()
        if not after.startswith(before): raise ValueError('review_receiver_prefix_changed')
        delta = parse_rollout(after[len(before):])
        actual = [row['payload'] for row in delta.rows if row['type'] == 'response_item']
        proof = import_evidence(actual, [item])
        if not delta.metadata['parse_complete'] or not proof['matched']:
            raise ValueError('review_receiver_facts_changed')
        save(Path(destination) / 'capsule-import.json', proof)
        return session
    except BaseException:
        session.close()
        raise
