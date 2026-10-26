"""Exercise the actual fresh review receiver hook without generation."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_review_capsule import open_receiver, verify
from native_evidence import read, save
from native_rollout_snapshot import capture_rollout
from native_cold_access import _check

AREA = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
OUT = AREA / 'capsule-receiver-admission-v2'
OUT.mkdir(exist_ok=False)
hot = read(AREA / 'review-capsule/facts.json')
index = verify(hot)
reg = read(AREA / 'review-registration.json')['session']
session = open_receiver(reg, OUT / 'receiver', hot)
try:
    snap = capture_rollout(session.opened['thread']['path'])
    assert not any(row['type'] == 'token_usage_record' for row in snap.rows)
    assert not any(row['payload'].get('history_base') for row in snap.rows if row['type'] == 'session_meta')
    assert session.opened['sandbox']['type'] == 'readOnly'
    entries = [(hot['cold_index']['path'], hot['cold_index']['sha256']),
        *[(row['path'], row['sha256']) for row in index['receipts']]]
    _check(session, entries, OUT / 'cold-access')
    assert session.source_manifest() == reg['initial_manifest']
finally:
    cleanup = session.close()
assert cleanup['empty_confirmed']
save(OUT / 'result.json', dict(passed=True, native_start_without_history_base=True,
    read_only=True, source_unchanged=True, model_calls=0, cleanup=cleanup,
    scope='Actual new receiver hook and cold evidence access only; no model delivery proof'))
print(dict(passed=True, read_only=True, inherited_development_history=False, model_calls=0))
