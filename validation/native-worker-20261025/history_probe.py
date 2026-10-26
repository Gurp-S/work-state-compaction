"""One registered zero-inference materialization check after lazy-idle discovery."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_owned_process import OwnedNativeRPC
from native_evidence import save, file_hash, records
from native_rollout_snapshot import capture_rollout

AREA = Path('D:/agent-task-runs/wsc-native-history-materialization-20261025-v1')
EXE = Path('C:/Users/48522/AppData/Local/OpenAI/Codex/bin/2993767bd1dfb009/codex.exe')
AREA.mkdir()
work = AREA / 'workspace'
work.mkdir()
item = {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': json.dumps({
    'kind': 'experimental_execution_binding', 'current_workspace': str(work), 'execution_mode': 'workspace_write',
    'observation': 'Local preflight; no task execution has started.'}, sort_keys=True)}]}
save(AREA / 'registration.json', dict(executable=str(EXE), executable_sha256=file_hash(EXE),
    allowed_methods=['initialize', 'initialized', 'thread/start', 'thread/inject_items'],
    injection=item, inference_calls_allowed=0, purpose='zero_inference_history_materialization_probe'))
server, opened = None, None
result = dict(status='running', calls=[])
try:
    server = OwnedNativeRPC(EXE, cwd=work, stderr_path=AREA / 'stderr.txt',
                            settings=['features.multi_agent=false', 'model_reasoning_effort="max"'])
    result['calls'].append('initialize')
    result['initialized'] = server.call('initialize', {'clientInfo': {'name': 'wsc_matrix_preflight', 'version': '1'},
        'capabilities': {'experimentalApi': True}})
    server.send({'method': 'initialized'})
    result['calls'].append('initialized')
    result['calls'].append('thread/start')
    opened = server.call('thread/start', {'cwd': str(work), 'model': 'gpt-6-luna', 'allowProviderModelFallback': False,
        'approvalPolicy': 'never', 'sandbox': 'workspace-write', 'runtimeWorkspaceRoots': [str(work)],
        'ephemeral': False, 'dynamicTools': []})
    save(AREA / 'thread-start.json', opened)
    path = Path(opened['thread']['path'])
    result['idle_path_existed'] = path.exists()
    result['calls'].append('thread/inject_items')
    response = server.call('thread/inject_items', {'threadId': opened['thread']['id'], 'items': [item]})
    save(AREA / 'inject-result.json', response)
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    result['path_exists_after_injection'] = path.exists()
    if path.exists():
        snapshot = capture_rollout(path, archive=AREA / 'rollout.jsonl')
        result['snapshot'] = snapshot.metadata
        result['response_receipts'] = sum(r['type'] == 'token_usage_record' for r in snapshot.rows)
        result['task_starts'] = sum(r['type'] == 'event_msg' and r['payload'].get('type') == 'task_started' for r in snapshot.rows)
        assert not result['response_receipts'] and not result['task_starts']
        result['status'] = 'materialized_without_inference'
    else:
        result['status'] = 'native_history_not_materialized'
except Exception as error:
    result.update(status='failed', error=type(error).__name__ + ':' + str(error))
finally:
    if server:
        result['cleanup'] = server.close()
    if opened:
        result['path_exists_after_close'] = Path(opened['thread']['path']).exists()
    save(AREA / 'result.json', result)
print(json.dumps(result, ensure_ascii=False))
