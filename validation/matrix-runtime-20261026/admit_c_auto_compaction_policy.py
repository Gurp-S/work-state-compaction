"""Zero-inference readback through the actual C-only policy hook."""
from pathlib import Path
import math
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_host_controls import settings
from native_owned_process import OwnedNativeRPC

PARENT = Path('D:/agent-task-runs/native-post-compaction-access-20261026-v1')
OUT = Path('D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
proof = PARENT / 'audit.json'
reg = {**read(proof)['native_session'], 'workspace': str(WORK), 'study_arm': 'C',
    'native_c_auto_compaction': dict(token_limit=96000, qualification_path=str(proof), qualification_sha256=file_hash(proof))}
assert file_hash(reg['executable']) == reg['executable_sha256']
parent_hash = file_hash(PARENT / 'next-admission-envelope.json')
startup = settings(reg)
control = {key: value for key, value in reg.items() if key != 'native_c_auto_compaction'}
control['study_arm'] = 'B'
assert settings(control) == startup[:-1] and startup[-1] == 'model_auto_compact_token_limit=96000'
save(OUT / 'registration.json', reg)
server = None
result = dict(model_calls=0, turn_started=False, native_B_changed=False, application_qualified=False,
    source_qualification_sha256=file_hash(proof), startup_flags=startup)
begin = time.monotonic()
try:
    server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / 'stderr.txt', settings=startup)
    server.call('initialize', dict(clientInfo=dict(name='C_policy_readback', version='1'), capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    observed = server.call('config/read', dict(cwd=str(WORK), includeLayers=False))
    assert observed['config'].get('model_auto_compact_token_limit') == 96000
    result['effective_limit'] = 96000
    result['origin'] = observed['origins'].get('model_auto_compact_token_limit')
except Exception as exc:
    result['error'] = type(exc).__name__ + ':' + str(exc)
finally:
    result['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    result['seconds'] = time.monotonic() - begin
    assert file_hash(PARENT / 'next-admission-envelope.json') == parent_hash
    result['implementation_sha256'] = {name: file_hash(ROOT / name) for name in
        ('experiments/native_c_auto_compaction.py', 'experiments/native_host_controls.py',
         'experiments/native_application_worker.py', 'tests/test_native_c_auto_compaction.py')}
    save(OUT / 'result.json', result)
    parent = read(PARENT / 'next-admission-envelope.json')
    save(OUT / 'next-admission-envelope.json', dict(remaining_limits={**parent['remaining_limits'],
        'max_seconds': parent['remaining_limits']['max_seconds'] - math.ceil(result['seconds'])},
        new_known=dict(tokens=0, responses=0), model_calls=0,
        parent_envelope_sha256=parent_hash, old_unknowns_preserved=True, whole_campaign_usage_complete=False,
        scope='Conservative admission only, not cash balance or upper bound of historical unknown spend'))
print(result)
