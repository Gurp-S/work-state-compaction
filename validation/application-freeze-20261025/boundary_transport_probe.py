"""Zero-inference native full-parent/initial-parent forks and read-only selector open.

Uses the already paid protocol thread, not an application experiment. No native
compaction or model-generated WSC selection is performed or credited.
"""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_owned_process import OwnedNativeRPC
from native_fork_history import observe_fork_bytes
from native_rollout_snapshot import capture_rollout
from native_evidence import read, save, file_hash, digest, import_evidence

AREA = Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1')
OLD = Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1')
AREA.mkdir()
reg = read(OLD / 'registration.json')
paid = read(OLD / 'result.json')['phase']
parent = read(OLD / 'session/thread-start.json')['thread']
source = capture_rollout(parent['path'], archive=AREA / 'parent-before.jsonl')
raw = (AREA / 'parent-before.jsonl').read_bytes()
assert source.metadata['sha256'] == paid['rollout_snapshot']['sha256']
save(AREA / 'registration.json', dict(executable=reg['executable'], executable_sha256=reg['executable_sha256'],
    parent_thread_id=parent['id'], parent_path=parent['path'], parent_sha256=source.metadata['sha256'],
    before_turn_id=paid['turn_accounting']['turn_id'], model=reg['model'], effort=reg['effort'],
    allowed_methods=['initialize', 'initialized', 'thread/fork', 'thread/inject_items', 'thread/start'],
    inference_calls_allowed=0, automatic_retries=0, native_compactions_allowed=0))
opened, observations, server = {}, {}, None
outcome = dict(status='running', new_responses=0, paid_BC_started=False)
try:
    assert file_hash(reg['executable']) == reg['executable_sha256']
    server = OwnedNativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA / 'stderr.txt',
        settings=['features.multi_agent=false', 'model_reasoning_effort="max"'])
    server.call('initialize', {'clientInfo': {'name': 'wsc_boundary_transport_probe', 'version': '1'},
        'capabilities': {'experimentalApi': True}})
    server.send({'method': 'initialized'})
    for name in ('full_parent', 'initial_parent'):
        params = dict(threadId=parent['id'], cwd=reg['workspace'], model=reg['model'],
            approvalPolicy='never', sandbox='workspace-write', runtimeWorkspaceRoots=[reg['workspace']],
            ephemeral=False, excludeTurns=True, deferGoalContinuation=True)
        if name == 'initial_parent':
            params['beforeTurnId'] = paid['turn_accounting']['turn_id']
        result = server.call('thread/fork', params, timeout=35)
        opened[name] = result
        area = AREA / name
        area.mkdir()
        save(area / 'fork.json', result)
        snapshot = capture_rollout(result['thread']['path'], archive=area / 'before.jsonl')
        meta = next(r['payload'] for r in snapshot.rows if r['type'] == 'session_meta')
        base = meta['history_base']
        end = base['end_byte_offset']
        assert base['thread_id'] == parent['id'] and 0 < end <= len(raw)
        binding = dict(child_sha256=snapshot.metadata['sha256'], parent=dict(path=str(AREA / 'parent-before.jsonl'),
            thread_id=parent['id'], end_byte_offset=end, end_ordinal_exclusive=base['end_ordinal_exclusive'],
            prefix_sha256=sha256(raw[:end]).hexdigest()))
        observed = observe_fork_bytes((area / 'before.jsonl').read_bytes(), binding)
        inherited_paid = [r for r in observed['inherited_rows'] if r['type'] == 'token_usage_record']
        assert len(inherited_paid) == (1 if name == 'full_parent' else 0)
        assert not any(r['type'] == 'token_usage_record' for r in observed['local_rows'])
        observations[name] = dict(settings={key: result.get(key) for key in (
            'model', 'modelProvider', 'reasoningEffort', 'cwd', 'approvalPolicy', 'sandbox', 'runtimeWorkspaceRoots')},
            base_instructions=meta.get('base_instructions'), dynamic_tools=meta.get('dynamic_tools'))
        save(area / 'binding.json', binding)
        save(area / 'observation.json', dict(history=observed['evidence'], inherited_responses=len(inherited_paid)))
        if name == 'initial_parent':
            item = dict(type='message', role='assistant', phase='commentary', content=[dict(type='output_text', text=json.dumps({
                'kind': 'boundary_transport_observation', 'source_phase_sha256': paid['rollout_snapshot']['sha256'],
                'known_completed_responses': 1}, sort_keys=True))])
            server.call('thread/inject_items', {'threadId': result['thread']['id'], 'items': [item]})
            after = capture_rollout(result['thread']['path'], archive=area / 'after.jsonl')
            updated = observe_fork_bytes((area / 'after.jsonl').read_bytes(), {**binding, 'child_sha256': after.metadata['sha256']})
            assert import_evidence(updated['items'][-1:], [item])['matched']
            assert not any(r['type'] == 'token_usage_record' for r in updated['local_rows'])
    assert observations['full_parent'] == observations['initial_parent'], 'fork_host_controls_differ'
    selector = server.call('thread/start', dict(cwd=reg['workspace'], model=reg['model'],
        allowProviderModelFallback=False, approvalPolicy='never', sandbox='read-only',
        runtimeWorkspaceRoots=[reg['workspace']], ephemeral=False, dynamicTools=[]), timeout=35)
    opened['selector'] = selector
    save(AREA / 'selector-start.json', selector)
    assert selector['sandbox']['type'] == 'readOnly' and selector['model'] == reg['model']
    outcome.update(status='native_fork_import_and_readonly_open_verified', matched_control_sha256=digest(observations['full_parent']),
        selector_sandbox=selector['sandbox'], inherited_full_parent_responses=1, inherited_initial_parent_responses=0,
        scope='Native transport only; not compaction, selection generation, write-denial enforcement or provider wire equivalence')
except Exception as error:
    outcome.update(status='failed', error=type(error).__name__ + ':' + str(error))
finally:
    if server:
        outcome['cleanup'] = server.close()
    outcome['parent_unchanged'] = file_hash(parent['path']) == source.metadata['sha256']
    save(AREA / 'result.json', outcome)
print(json.dumps(outcome))
