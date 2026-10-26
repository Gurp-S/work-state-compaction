"""Observe native fork resume counters before any new inference."""
from pathlib import Path
import json
import queue
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest, digest
from native_rollout_snapshot import capture_rollout
from run_native_pair import NativeRPC, initialize, SETTINGS

AREA = Path('D:/agent-task-runs/wsc-fork-admission-20261023-v1')
AREA.mkdir()
old = Path('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1')
fork = read(old / 'by-turn/fork1/response.json')
reg = read('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1/registration.json')
path = Path(fork['thread']['path'])
before = capture_rollout(path, archive=AREA / 'before.jsonl')
workspace_before = manifest(reg['workspace'])
save(AREA / 'registration.json', {'scope': 'Resume notification/counter observation only',
    'thread_id': fork['thread']['id'], 'path': str(path), 'before_sha256': before.metadata['sha256'],
    'executable': reg['executable'], 'executable_sha256': file_hash(reg['executable']),
    'workspace': reg['workspace'], 'workspace_manifest_sha256': digest(workspace_before),
    'script_sha256': file_hash(__file__), 'inference_budget': 0,
    'permission_mode': 'read-only for protocol observation; not a task-performance comparison'})
events, result = [], {'status': 'started', 'new_model_calls': 0}
try:
    with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA / 'stderr.txt', settings=SETTINGS) as server:
        initialize(server)
        response = server.call('thread/resume', {'threadId': fork['thread']['id'], 'excludeTurns': True,
            'model': reg['model'], 'cwd': reg['workspace'], 'approvalPolicy': 'never', 'sandbox': 'read-only'}, timeout=40)
        save(AREA / 'resume.json', response)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try: events.append(server.event(timeout=min(.2, deadline-time.monotonic())))
            except queue.Empty: pass
        save(AREA / 'notifications.json', events)
        result.update(status='resume_observed', methods=[e.get('method') for e in events],
                      token_notifications=[e for e in events if e.get('method') == 'thread/tokenUsage/updated'])
except Exception as exc:
    result.update(status='stopped', error=type(exc).__name__ + ':' + str(exc))
finally:
    after = capture_rollout(path, archive=AREA / 'after.jsonl')
    assert not any(r['type'] == 'token_usage_record' for r in after.rows)
    assert manifest(reg['workspace']) == workspace_before
    result.update(workspace_unchanged=True, before_sha256=before.metadata['sha256'],
                  after_sha256=after.metadata['sha256'], new_local_usage_records=0)
    save(AREA / 'result.json', result)
    print(json.dumps(result), flush=True)
