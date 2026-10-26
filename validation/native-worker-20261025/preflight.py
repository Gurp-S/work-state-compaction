"""Four actual native app servers, no turn or compaction calls and no inference."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_owned_process import OwnedNativeRPC
from native_evidence import save, file_hash, records

AREA = Path('D:/agent-task-runs/wsc-native-parallel-preflight-20261025-v1')
EXE = Path('C:/Users/48522/AppData/Local/OpenAI/Codex/bin/2993767bd1dfb009/codex.exe')
MODEL = 'gpt-6-luna'
SETTINGS = ['features.multi_agent=false', 'model_reasoning_effort="max"']
AREA.mkdir(exist_ok=False)
save(AREA / 'registration.json', dict(executable=str(EXE), executable_sha256=file_hash(EXE), model=MODEL,
    effort='max', settings=SETTINGS, parallel_servers=4, purpose='zero_inference_native_worker_preflight',
    allowed_methods=['initialize', 'initialized', 'thread/start'], turn_calls_allowed=False,
    inference_calls_allowed=0, source_sha256=file_hash(ROOT / 'experiments/native_owned_process.py')))
barrier = threading.Barrier(4)


def invoke(index):
    area = AREA / str(index)
    area.mkdir()
    work = area / 'workspace'
    work.mkdir()
    (work / 'README.md').write_text('Local execution preflight fixture.\n', encoding='utf8')
    server, opened = None, None
    result = dict(index=index, state='starting', calls=[])
    try:
        server = OwnedNativeRPC(EXE, cwd=work, stderr_path=area / 'stderr.txt', settings=SETTINGS)
        result['server_pid'] = server.proc.pid
        result['calls'].append('initialize')
        result['initialized'] = server.call('initialize', {'clientInfo': {'name': 'wsc_matrix_preflight', 'version': '1'},
            'capabilities': {'experimentalApi': True}}, timeout=35)
        server.send({'method': 'initialized'})
        result['calls'].append('initialized')
        result['calls'].append('thread/start')
        opened = server.call('thread/start', {'cwd': str(work), 'model': MODEL, 'allowProviderModelFallback': False,
            'approvalPolicy': 'never', 'sandbox': 'workspace-write', 'runtimeWorkspaceRoots': [str(work)],
            'ephemeral': False, 'dynamicTools': []}, timeout=35)
        save(area / 'thread-start.json', opened)
        result['observed_configuration'] = {k: opened.get(k) for k in ('model', 'modelProvider', 'reasoningEffort',
            'approvalPolicy', 'sandbox', 'cwd', 'runtimeWorkspaceRoots')}
        assert opened['model'] == MODEL and opened['reasoningEffort'] == 'max'
        assert opened['approvalPolicy'] == 'never' and opened['sandbox']['type'] == 'workspaceWrite'
        assert Path(opened['cwd']).resolve() == work.resolve()
        result['owned_members'] = server.owner.members()
        barrier.wait(timeout=40)
        result['four_servers_ready_together'] = True
        result['state'] = 'zero_inference_preflight_passed'
    except Exception as error:
        barrier.abort()
        result.update(state='failed', error=type(error).__name__ + ':' + str(error))
    finally:
        if server:
            try:
                result['cleanup'] = server.close()
            except Exception as error:
                result.update(state='failed', cleanup_error=str(error))
        if opened and opened['thread'].get('path'):
            path = Path(opened['thread']['path'])
            if path.exists():
                raw = path.read_bytes()
                (area / 'rollout.jsonl').write_bytes(raw)
                rows = records(area / 'rollout.jsonl')
                result['model_receipts'] = sum(r['type'] == 'token_usage_record' for r in rows)
                result['task_starts'] = sum(r['type'] == 'event_msg' and r['payload'].get('type') == 'task_started' for r in rows)
                result['rollout_sha256'] = file_hash(area / 'rollout.jsonl')
                if result['model_receipts'] or result['task_starts']:
                    result.update(state='failed', unexpected_inference=True)
            else:
                result.update(state='failed', rollout_missing=True)
        save(area / 'result.json', result)
    return result


with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(invoke, range(4)))
result = dict(status='passed' if all(i['state'] == 'zero_inference_preflight_passed' for i in results) else 'failed',
    servers=results, automatic_retries=0, paid_comparison_started=False,
    scope='Native concurrency, observed settings and owned cleanup; no model execution, host equivalence or C qualification')
save(AREA / 'result.json', result)
print(json.dumps(dict(status=result['status'], servers=[dict(index=r['index'], state=r['state'],
    error=r.get('error'), cleanup=r.get('cleanup'), model_receipts=r.get('model_receipts')) for r in results]), ensure_ascii=False))
