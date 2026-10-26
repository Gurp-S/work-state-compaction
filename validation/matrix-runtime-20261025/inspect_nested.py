"""Observe nested-fork byte/ordinal semantics before implementing three boundaries."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_owned_process import OwnedNativeRPC
from native_evidence import read, save, file_hash
from native_rollout_snapshot import capture_rollout, parse_rollout

AREA = Path('D:/agent-task-runs/wsc-nested-fork-observation-20261025-v1')
AREA.mkdir()
parent = read(Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1/full_parent/fork.json'))
old = read(Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1/registration.json'))
save(AREA / 'registration.json', dict(parent_thread_id=parent['thread']['id'], executable_sha256=file_hash(old['executable']),
    model=old['model'], max_forks=2, model_calls_allowed=0, purpose='nested_byte_and_ordinal_observation'))
server = OwnedNativeRPC(old['executable'], cwd=old['workspace'], stderr_path=AREA / 'stderr.txt', settings=['features.multi_agent=false', 'model_reasoning_effort="max"'])
results = []
try:
    server.call('initialize', {'clientInfo': {'name': 'wsc_nested_history_probe', 'version': '1'}, 'capabilities': {'experimentalApi': True}})
    server.send({'method': 'initialized'})
    for index in range(2):
        before = capture_rollout(parent['thread']['path'], archive=AREA / f'parent-{index}.jsonl')
        pmeta = next(r['payload'] for r in before.rows if r['type'] == 'session_meta')
        child = server.call('thread/fork', dict(threadId=parent['thread']['id'], cwd=old['workspace'], model=old['model'],
            approvalPolicy='never', sandbox='workspace-write', runtimeWorkspaceRoots=[old['workspace']],
            ephemeral=False, excludeTurns=True, deferGoalContinuation=True))
        save(AREA / f'fork-{index}.json', child)
        after = capture_rollout(child['thread']['path'], archive=AREA / f'child-{index}.jsonl')
        meta = next(r['payload'] for r in after.rows if r['type'] == 'session_meta')
        base = meta['history_base']
        prefix = Path(parent['thread']['path']).read_bytes()[:base['end_byte_offset']]
        rows = parse_rollout(prefix).rows
        assert not any(r['type'] == 'token_usage_record' for r in after.rows)
        results.append(dict(parent_id=parent['thread']['id'], parent_history_base=pmeta.get('history_base'),
            child_history_base=base, physical_prefix_records=len(rows), parent_file_sha256=before.metadata['sha256'],
            child_file_sha256=after.metadata['sha256'], parent_path=parent['thread']['path'], child_path=child['thread']['path']))
        parent = child
finally:
    cleanup = server.close()
save(AREA / 'result.json', dict(observations=results, cleanup=cleanup, model_calls=0))
print(json.dumps(results))
