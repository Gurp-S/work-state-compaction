"""Review native lifecycle and transport receipts without repeating inference."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest

owner = read(HERE / 'owner-check.json')
assert owner['baseline']['child_alive_after_parent_exit']
assert owner['baseline']['fixture_child_cleanup_confirmed'] and owner['candidate']['cleanup']['empty_confirmed']
assert owner['source_sha256'] == file_hash(ROOT / 'experiments/native_owned_process.py')
parallel = Path('D:/agent-task-runs/wsc-native-parallel-preflight-20261025-v1')
initial = read(parallel / 'result.json')
assert initial['status'] == 'failed'  # Preserve the original conservative archive failure.
members = []
for server in initial['servers']:
    assert server['four_servers_ready_together'] and server['rollout_missing']
    assert server['cleanup']['empty_confirmed']
    assert server['calls'] == ['initialize', 'initialized', 'thread/start']
    assert server['server_pid'] in server['owned_members']
    assert not set(server['owned_members']) & set(members)
    members.extend(server['owned_members'])
    assert server['observed_configuration']['model'] == 'gpt-6-luna'
    assert server['observed_configuration']['reasoningEffort'] == 'max'
save(parallel / 'reviewed-result.json', dict(
    status='four_server_concurrency_and_cleanup_verified_idle_history_absent',
    original_result_sha256=file_hash(parallel / 'result.json'), concurrent_servers=4,
    calls_exclude_turn_or_compact=True, observed_idle_rollouts_absent=True,
    full_host_equivalence_proven=False, paid_comparison_started=False))

history_area = Path('D:/agent-task-runs/wsc-native-history-materialization-20261025-v1')
history = read(history_area / 'result.json')
assert not history['idle_path_existed'] and history['path_exists_after_injection']
assert history['status'] == 'materialized_without_inference'
assert history['response_receipts'] == history['task_starts'] == 0
assert history['snapshot']['sha256'] == file_hash(history_area / 'rollout.jsonl')
assert history['cleanup']['empty_confirmed']

fixtures = read(HERE / 'session-fixture-checks.json')
assert fixtures['passed'] and fixtures['tests'] == 2
assert fixtures['source_sha256'] == file_hash(ROOT / 'experiments/native_application_session.py')
opened_area = Path('D:/agent-task-runs/wsc-native-application-open-20261025-v1')
opened = read(opened_area / 'result.json')
assert opened['status'] == 'opened_without_inference' and opened['cleanup']['empty_confirmed']
assert opened['opened_sha256'] == file_hash(opened_area / 'session/opened.jsonl')

paid_area = Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1')
paid = read(paid_area / 'result.json')
reg = read(paid_area / 'registration.json')
assert all(file_hash(path) == value for path, value in reg['source_pins'].items())
assert file_hash(reg['executable']) == reg['executable_sha256']
phase = paid['phase']
assert phase['completed'] and phase['failure'] is None and phase['usage_complete']
assert phase['turn_accounting']['complete'] and not phase['turn_accounting']['reasons']
assert phase['rollout_snapshot']['sha256'] == file_hash(paid_area / 'phase/rollout.jsonl')
assert read(paid_area / 'journal/000.json') == phase and paid['journal_entries'] == 1
assert phase['receipts']['response_count'] == 1 and paid['workspace_unchanged']
assert paid['cleanup']['empty_confirmed'] and json.loads(phase['finals'][0]['text']) == {'ready': True}
receipt = phase['receipts']['response_receipts'][0]
assert receipt['usage']['total_tokens'] == 22567
assert manifest(Path(reg['workspace'])) == reg['initial_manifest']

inputs_area = Path('D:/agent-task-runs/wsc-four-app-inputs-20261025-v1')
inputs = read(inputs_area / 'result.json')
assert len(inputs['tasks']) == 4 and inputs['original_source_unchanged']
for item in inputs['tasks']:
    assert file_hash(item['binding']) == item['binding_sha256']
    binding = read(item['binding'])
    assert manifest(Path(binding['workspace'])) == binding['source_manifest']

review = dict(status='native_execution_layer_reviewed_not_full_matrix_worker',
    current_executable=dict(path=reg['executable'], sha256=reg['executable_sha256'], version='0.164.0-alpha.11.1'),
    observed_model=reg['model'], effort=reg['effort'], concurrent_native_servers=4,
    parent_only_supervision_gap_reproduced=True, private_job_child_cleanup_verified=True,
    observed_owned_members_at_parallel_barrier=len(members), zero_inference_history_materialization_verified=True,
    stage_fixture_checks=2, paid_protocol_responses=1, paid_protocol_usage=receipt['usage'],
    paid_protocol_seconds=phase['seconds'], paid_protocol_cash=None, input_tasks_frozen=4,
    paid_comparison_started=False, goal_complete=False,
    receipts={name: dict(path=str(path), sha256=file_hash(path)) for name, path in {
        'parallel_review': parallel / 'reviewed-result.json', 'history_probe': history_area / 'result.json',
        'new_session_open': opened_area / 'result.json', 'paid_probe': paid_area / 'result.json',
        'frozen_inputs': inputs_area / 'result.json'}.items()},
    remaining=['A3 frozen workspace/dependencies', 'full paired host admission', 'matrix worker stage/boundary coordination',
               'C candidate and three boundary policy', 'cumulative per-arm/study budgets', 'final quality review adapter',
               'external author-read access boundary'],
    limits=['Windows job attached before RPC handshake, not suspended process creation; no universal pre-attach descendant claim',
            'Paid smoke has no tools or compaction; not a tool-heavy or multi-stage application proof',
            'Native idle history absence is corrected via separate zero-inference materialization, not overwritten',
            'Input contents frozen; absence of external reads is not proven'])
save(HERE / 'review.json', review)
print(json.dumps({k: review[k] for k in ('status', 'concurrent_native_servers', 'paid_protocol_responses',
                                       'paid_protocol_usage', 'paid_protocol_seconds', 'input_tasks_frozen')}))
