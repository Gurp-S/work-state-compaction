"""No-inference process inventory; topology alone is not a quiescence proof."""
from pathlib import Path
import json
import math
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings

PARENT = Path('D:/agent-task-runs/native-controlled-stop-20261026-v1')
OUT = Path('D:/agent-task-runs/native-idle-process-inventory-20261026-v1')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
reg = {**read(PARENT / 'registration.json')['session'], 'workspace': str(WORK)}
assert file_hash(reg['executable']) == reg['executable_sha256']
old = {name: file_hash(PARENT / name) for name in ('result.json', 'next-admission-envelope.json')}
server = None
result = dict(model_calls=0, turn_started=False, quiescence_proven=False)
begin = time.monotonic()

def inventory():
    members = server.owner.members()
    # Numeric PIDs only, no command lines, credentials or environment values.
    selection = ','.join(str(int(pid)) for pid in members)
    command = ('Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @(' + selection +
        ') } | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CreationDate | ConvertTo-Json -Depth 3 -Compress')
    completed = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, encoding='utf-8', check=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    records = json.loads(completed.stdout) if completed.stdout.strip() else []
    if isinstance(records, dict):
        records = [records]
    return dict(members=members, processes=records,
        membership_complete={r['ProcessId'] for r in records} == set(members))

try:
    server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / 'stderr.txt', settings=settings(reg))
    server.call('initialize', dict(clientInfo=dict(name='idle_inventory', version='1'), capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    result['initialized'] = inventory()
    thread = server.call('thread/start', dict(cwd=str(WORK), model=reg['model'], allowProviderModelFallback=False,
        approvalPolicy='never', sandbox='read-only', runtimeWorkspaceRoots=[str(WORK)], ephemeral=False, dynamicTools=[]))
    result['idle_thread_id'] = thread['thread']['id']
    result['prepared_idle'] = inventory()
except Exception as exc:
    result['error'] = type(exc).__name__ + ':' + str(exc)
finally:
    result['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    result['elapsed_seconds'] = time.monotonic() - begin
    assert all(file_hash(PARENT / name) == value for name, value in old.items())
    result['parent_sha256'] = old
    save(OUT / 'result.json', result)
    envelope = read(PARENT / 'next-admission-envelope.json')
    envelope = {**envelope, 'remaining_limits': {**envelope['remaining_limits'],
        'max_seconds': envelope['remaining_limits']['max_seconds'] - math.ceil(result['elapsed_seconds'])},
        'parent_envelope_sha256': old['next-admission-envelope.json'], 'inventory_model_calls': 0}
    save(OUT / 'next-admission-envelope.json', envelope)
print(json.dumps(result, ensure_ascii=False))
