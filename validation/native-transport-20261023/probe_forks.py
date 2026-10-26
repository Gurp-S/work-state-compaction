"""Zero-inference native forks of one archived compacted boundary.

No resume of the original thread, no imported/reconstructed reasoning, no task
execution and no configuration/prompt edits. Forked history is only hashed.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, digest, manifest, state
from native_rollout_snapshot import capture_rollout
from run_native_pair import NativeRPC, initialize, SETTINGS

AREA = Path('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1')
OLD = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
reg = read(OLD / 'registration.json')
source = OLD / 'B/compaction1/rollout.jsonl'
snapshot = capture_rollout(source)
assert snapshot.metadata['parse_complete']
source_meta = next(r['payload'] for r in snapshot.rows if r['type'] == 'session_meta')
compacted = [r['payload'] for r in snapshot.rows if r['type'] == 'compacted'][-1]
source_ids = {r['payload']['response_id'] for r in snapshot.rows if r['type'] == 'token_usage_record'}
assert not any('goal' in r['type'].lower() for r in snapshot.rows)
source_copy = AREA / 'source-boundary.jsonl'
with source_copy.open('xb') as stream:
    stream.write(source.read_bytes())
before = manifest(reg['workspace'])
save(AREA / 'registration.json', {'scope': 'Native fork transport only; zero model execution',
    'source': str(source), 'source_sha256': file_hash(source), 'copy_sha256': file_hash(source_copy),
    'executable': reg['executable'], 'executable_sha256': file_hash(reg['executable']),
    'workspace': reg['workspace'], 'workspace_manifest_sha256': digest(before), 'settings': SETTINGS,
    'source_response_ids': sorted(source_ids), 'script_sha256': file_hash(__file__),
    'permitted_methods': ['initialize', 'thread/fork'], 'inference_budget': 0, 'fork_count': 2})
results, opened = {}, {}
outcome = {'status': 'started', 'new_model_calls': 0}
try:
    with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA / 'stderr.txt', settings=SETTINGS) as server:
        initialize(server)
        save(AREA / 'process.json', {'pid': server.proc.pid})
        for name in ('fork1', 'fork2'):
            params = {'threadId': source_meta['id'], 'path': str(source_copy), 'model': reg['model'],
                'cwd': reg['workspace'], 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                'runtimeWorkspaceRoots': [reg['workspace']], 'ephemeral': False,
                'excludeTurns': True, 'deferGoalContinuation': True}
            save(AREA / name / 'request.json', params)
            response = server.call('thread/fork', params, timeout=45)
            opened[name] = response
            save(AREA / name / 'response.json', response)
            observed = capture_rollout(response['thread']['path'], archive=AREA / name / 'rollout.jsonl')
            assert observed.metadata['parse_complete']
            actual_compacted = [r['payload'] for r in observed.rows if r['type'] == 'compacted']
            ids = {r['payload']['response_id'] for r in observed.rows if r['type'] == 'token_usage_record'}
            assert ids == source_ids, 'new_or_missing_response_receipt'
            assert actual_compacted, 'fork_compaction_missing'
            actual = actual_compacted[-1]
            fields = {k: {'equal': actual.get(k) == v, 'source_sha256': digest(v),
                          'fork_sha256': digest(actual.get(k))} for k, v in compacted.items()}
            meta = next(r['payload'] for r in observed.rows if r['type'] == 'session_meta')
            results[name] = {'thread_id': response['thread']['id'], 'rollout_sha256': observed.metadata['sha256'],
                'source_thread_not_reused': response['thread']['id'] != source_meta['id'],
                'compaction_fields': fields, 'canonical_items_equal': state(observed.rows) == state(snapshot.rows),
                'base_instructions_equal': meta.get('base_instructions') == source_meta.get('base_instructions'),
                'native_configuration': {k: response.get(k) for k in ('model', 'modelProvider', 'reasoningEffort',
                    'cwd', 'sandbox', 'approvalPolicy', 'serviceTier', 'runtimeWorkspaceRoots')},
                'new_response_ids': sorted(ids - source_ids), 'inherited_response_count': len(ids)}
            save(AREA / name / 'audit.json', results[name])
            print(json.dumps({'fork': name, 'new_responses': len(ids-source_ids),
                'canonical_items_equal': results[name]['canonical_items_equal'],
                'different_compaction_fields': [k for k,v in fields.items() if not v['equal']]}), flush=True)
        outcome['status'] = 'transport_observed'
except Exception as exc:
    outcome.update(status='stopped', error=type(exc).__name__ + ':' + str(exc))
finally:
    # The original workspace and archived boundary are never restored or edited.
    outcome.update(source_unchanged=file_hash(source) == snapshot.metadata['sha256'],
        source_copy_unchanged=file_hash(source_copy) == snapshot.metadata['sha256'],
        workspace_unchanged=manifest(reg['workspace']) == before, forks=results,
        process_terminal=True, scope='Zero-inference archival fidelity; not model-visible request equivalence or task quality')
    save(AREA / 'result.json', outcome)
    print(json.dumps({k:v for k,v in outcome.items() if k != 'forks'}), flush=True)
