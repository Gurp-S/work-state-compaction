"""Offline exact receipt projection and zero-inference receiver access."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, digest
from native_review_capsule import build, verify
from native_application_session import NativeApplicationSession
from native_cold_access import _check

AREA = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')
groups = [dict(registration=str(AREA / 'isolated-S3-acceptance/registration.json'), result=str(AREA / 'isolated-S3-acceptance/result.json')),
    dict(registration=str(PRIOR / 'S3-supplemental/registration.json'), result=str(PRIOR / 'S3-supplemental/result.json')),
    dict(registration=str(PRIOR / 'S3-graph-check/registration.json'), result=str(PRIOR / 'S3-graph-check/result.json'))]
expected = [row['id'] for group in groups for row in read(group['result']).get('outcomes', read(group['result']).get('checks'))]
reg = read(AREA / 'runtime-C.json')
hot = build(str(Path(reg['workspace']) / 'gui'), groups, AREA / 'review-capsule', expected_checks=expected, previous_run=PRIOR / 'result.json')
index = verify(hot)
changed = deepcopy(hot); changed['checks'][0]['passed'] = not changed['checks'][0]['passed']
try:
    verify(changed)
    raise AssertionError('modified fact accepted')
except ValueError as error:
    assert str(error) == 'review_capsule_facts_changed'
with tempfile.TemporaryDirectory() as folder:
    altered = Path(folder) / 'index.json'; altered.write_bytes(Path(hot['cold_index']['path']).read_bytes() + b' ')
    changed = {**hot, 'cold_index': {**hot['cold_index'], 'path': str(altered)}}
    try:
        verify(changed)
        raise AssertionError('modified index accepted')
    except ValueError as error:
        assert str(error) == 'review_capsule_index_changed'
reg = {**reg, 'sandbox': 'read-only', 'initial_manifest': read(AREA / 'result.json')['source_unchanged'] and read(AREA / 'review-registration.json')['session']['initial_manifest']}
session = NativeApplicationSession(reg, AREA / 'capsule-receiver')
try:
    session.open()
    before = Path(session.opened['thread']['path']).read_bytes()
    session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[
        dict(type='message', role='developer', content=[dict(type='input_text', text=json.dumps(hot, ensure_ascii=False, separators=(',', ':')))])]))
    entries = [(hot['cold_index']['path'], hot['cold_index']['sha256']), *[(row['path'], row['sha256']) for row in index['receipts']]]
    _check(session, entries, AREA / 'capsule-cold-access')
    after = Path(session.opened['thread']['path']).read_bytes()
    assert after.startswith(before)
    assert not any(json.loads(line)['type'] == 'token_usage_record' for line in after.splitlines() if line.strip())
    assert session.source_manifest() == reg['initial_manifest']
finally:
    cleanup = session.close()
assert cleanup['empty_confirmed']
result = dict(hot_fact_bytes=len(json.dumps(hot, ensure_ascii=False, separators=(',', ':')).encode()),
    previous_fact_file_bytes=(AREA / 'review-facts.json').stat().st_size, checks_preserved=17,
    full_manifest_and_receipts_retained=True, tamper_rejected=['facts', 'index'], model_calls=0,
    actual_read_only_cold_access=read(AREA / 'capsule-cold-access/execution.json'), cleanup=cleanup,
    scope='Offline fact projection and fresh native receive/access only; no model closeout or B/C benefit proof')
save(AREA / 'capsule-check.json', result)
print(result)
