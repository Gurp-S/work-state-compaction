"""One bounded read-only protocol call, not a repeat of the historical task."""
from pathlib import Path
import json
import queue
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, digest, manifest, usage
from native_rollout_snapshot import capture_rollout
from native_fork_history import observe_registered_fork
from run_native_pair import NativeRPC, initialize, SETTINGS, MODEL

base = Path('D:/agent-task-runs/wsc-fork-admission-20261023-v1')
AREA = base / 'single-response-probe'
AREA.mkdir()
old = Path('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1')
fork = read(old / 'by-turn/fork1/response.json')
tid, path = fork['thread']['id'], Path(fork['thread']['path'])
config = read('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1/registration.json')
before_workspace = manifest(config['workspace'])
request = '本轮是只读运行协议测量，不继续此前编程任务。无需使用工具或查询资料。请仅回复这个JSON：{"protocol_probe":"received"}。'
save(AREA / 'registration.json', {'purpose': 'first_fork_receipt_protocol_measurement_not_task_qualification',
    'thread_id': tid, 'request': request, 'model': MODEL, 'effort': 'max',
    'stop_limits': {'responses': 1, 'seconds': 60, 'total_tokens': 100000},
    'executable_sha256': file_hash(config['executable']), 'script_sha256': file_hash(__file__),
    'workspace_manifest_sha256': digest(before_workspace), 'task_artifact_edits': False,
    'permission_mode': 'read-only', 'retry': False})
result = {'status': 'started', 'completed': False, 'failure': None, 'finals': []}
turn, before = None, None
try:
    with NativeRPC(config['executable'], cwd=config['workspace'], stderr_path=AREA / 'stderr.txt', settings=SETTINGS) as server:
        initialize(server)
        opened = server.call('thread/resume', {'threadId': tid, 'excludeTurns': True, 'model': MODEL,
            'cwd': config['workspace'], 'approvalPolicy': 'never', 'sandbox': 'read-only'}, timeout=40)
        save(AREA / 'resume.json', opened)
        assert opened['model'] == MODEL and opened['reasoningEffort'] == 'max' and opened['sandbox']['type'] == 'readOnly'
        before = capture_rollout(path, archive=AREA / 'before.jsonl')
        assert not any(r['type'] == 'token_usage_record' for r in before.rows)
        binding = read(old / 'history-binding.json')['binding']
        binding['child_sha256'] = before.metadata['sha256']
        history = observe_registered_fork(path, binding)
        save(AREA / 'history-binding.json', binding)
        parent_paid = [r['payload'] for r in history['inherited_rows'] if r['type'] == 'token_usage_record']
        parent_counts = [r['payload'].get('info') for r in history['inherited_rows'] if r['type'] == 'event_msg'
                         and r['payload'].get('type') == 'token_count']
        save(AREA / 'parent-counters.json', {'last_receipt': parent_paid[-1],
            'last_display': parent_counts[-1], 'response_ids': [p['response_id'] for p in parent_paid],
            'history_evidence': history['evidence']})
        began = time.monotonic()
        response = server.call('turn/start', {'threadId': tid, 'model': MODEL, 'effort': 'max',
            'input': [{'type': 'text', 'text': request}]})
        turn = response['turn']['id']
        save(AREA / 'turn-start.json', response)
        try:
            with (AREA / 'events.jsonl').open('x', encoding='utf-8') as log:
                while time.monotonic()-began < 60:
                    try: event = server.event(timeout=.5)
                    except queue.Empty: continue
                    log.write(json.dumps(event, ensure_ascii=False)+'\n');log.flush()
                    p, method = event.get('params', {}), event.get('method')
                    if p.get('threadId') not in (None, tid): continue
                    if method == 'error': raise ValueError('provider_error_no_retry')
                    if 'id' in event and method: raise ValueError('interactive_callback_not_registered')
                    if method == 'item/started' and p.get('item',{}).get('type') not in {'userMessage','agentMessage','reasoning','contextCompaction'}:
                        raise ValueError('nonmessage_activity_not_registered')
                    if method == 'item/completed' and p.get('item',{}).get('type') == 'agentMessage':
                        result['finals'].append(p['item'])
                    if method == 'thread/tokenUsage/updated':
                        ledger = usage(capture_rollout(path).rows, tid)
                        if ledger['response_count'] > 1 or ledger['all_usage']['total_tokens'] > 100000:
                            raise ValueError('registered_usage_cap')
                    if method == 'turn/completed' and p['turn']['id'] == turn:
                        result['completed'] = p['turn']['status'] == 'completed'
                        result['status'] = 'response_observed' if result['completed'] else 'stopped'
                        break
                else: raise ValueError('registered_wall_cap')
        except Exception as exc:
            result.update(status='stopped', failure=type(exc).__name__+':'+str(exc))
            server.call('turn/interrupt', {'threadId': tid, 'turnId': turn})
        result['seconds'] = time.monotonic()-began
except Exception as exc:
    result.update(status='stopped', failure=type(exc).__name__+':'+str(exc))
finally:
    after = capture_rollout(path, archive=AREA / 'after.jsonl')
    result.update(turn_id=turn, after_sha256=after.metadata['sha256'],
        receipts=usage(after.rows, tid), workspace_unchanged=manifest(config['workspace']) == before_workspace,
        accounting_complete='pending_counter_origin_review', cash=None)
    save(AREA / 'result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k not in {'receipts','finals'}}), flush=True)
    print(json.dumps({'responses':result['receipts']['response_count'], 'usage':result['receipts']['all_usage']}),flush=True)
