"""One supported by-id historical fork attempt after archived-path rejection."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, digest, manifest, state
from native_rollout_snapshot import capture_rollout
from run_native_pair import NativeRPC, initialize, SETTINGS

OLD = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
AREA = Path('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1/by-turn')
AREA.mkdir()
reg = read(OLD / 'registration.json')
source = capture_rollout(OLD / 'B/compaction1/rollout.jsonl')
source_meta = next(r['payload'] for r in source.rows if r['type'] == 'session_meta')
boundary = read(OLD / 'B/finite_task/phase-outcome.json')['usage_completion_evidence']['turn_id']
live = Path(read(OLD / 'initial/B/thread-start.json')['thread']['path'])
live_before = capture_rollout(live)
live_ids = {r['payload']['response_id'] for r in live_before.rows if r['type'] == 'token_usage_record'}
before = manifest(reg['workspace'])
compacted = [r['payload'] for r in source.rows if r['type'] == 'compacted'][-1]
params = {'threadId': source_meta['id'], 'beforeTurnId': boundary,
          'model': reg['model'], 'cwd': reg['workspace'], 'approvalPolicy': 'never',
          'sandbox': 'workspace-write', 'runtimeWorkspaceRoots': [reg['workspace']],
          'ephemeral': False, 'excludeTurns': True, 'deferGoalContinuation': True}
save(AREA / 'registration.json', {'source_thread_id': source_meta['id'], 'request': params,
    'source_boundary_sha256': source.metadata['sha256'], 'live_source_sha256': live_before.metadata['sha256'],
    'workspace_manifest_sha256': digest(before), 'executable_sha256': file_hash(reg['executable']),
    'script_sha256': file_hash(__file__), 'inference_budget': 0, 'maximum_forks': 2,
    'second_fork_condition': 'First fork preserves all compacted fields and canonical items exactly'})
result = {'status': 'started', 'forks': {}, 'new_model_calls': 0}
try:
    with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA / 'stderr.txt', settings=SETTINGS) as server:
        initialize(server)
        save(AREA / 'process.json', {'pid': server.proc.pid})
        for name in ('fork1', 'fork2'):
            response = server.call('thread/fork', params, timeout=45)
            save(AREA / name / 'response.json', response)
            observed = capture_rollout(response['thread']['path'], archive=AREA / name / 'rollout.jsonl')
            assert observed.metadata['parse_complete']
            ids = {r['payload']['response_id'] for r in observed.rows if r['type'] == 'token_usage_record'}
            assert ids <= live_ids, 'unregistered_response'
            compact_rows = [r['payload'] for r in observed.rows if r['type'] == 'compacted']
            actual = compact_rows[-1] if compact_rows else {}
            fields = {k: {'equal': actual.get(k) == v, 'expected_sha256': digest(v),
                          'actual_sha256': digest(actual.get(k))} for k,v in compacted.items()}
            equal = state(observed.rows) == state(source.rows)
            result['forks'][name] = {'thread_id': response['thread']['id'],
                'rollout_sha256': observed.metadata['sha256'], 'canonical_items_equal': equal,
                'canonical_items_count': len(state(observed.rows)), 'compacted_count': len(compact_rows),
                'compaction_fields': fields, 'new_response_ids': sorted(ids - live_ids),
                'inherited_response_ids': sorted(ids),
                'native_configuration': {k: response.get(k) for k in ('model','modelProvider','reasoningEffort',
                    'cwd','sandbox','approvalPolicy','serviceTier','runtimeWorkspaceRoots')}}
            save(AREA / name / 'audit.json', result['forks'][name])
            if not equal or not all(v['equal'] for v in fields.values()):
                result['status'] = 'historical_boundary_not_equivalent'
                break
        else:
            assert result['forks']['fork1']['native_configuration'] == result['forks']['fork2']['native_configuration']
            result['status'] = 'two_native_forks_preserve_registered_boundary'
except Exception as exc:
    result.update(status='stopped', error=type(exc).__name__ + ':' + str(exc))
finally:
    result.update(live_source_unchanged=file_hash(live) == live_before.metadata['sha256'],
                  archived_source_unchanged=file_hash(OLD / 'B/compaction1/rollout.jsonl') == source.metadata['sha256'],
                  workspace_unchanged=manifest(reg['workspace']) == before,
                  process_terminal=True, scope='Zero-inference native fork state; no claim of submitted model request equivalence')
    save(AREA / 'result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'forks'}), flush=True)
    for name, value in result['forks'].items():
        print(json.dumps({'fork': name, 'items_equal': value['canonical_items_equal'],
            'different_compaction_fields': [k for k,v in value['compaction_fields'].items() if not v['equal']]}), flush=True)
