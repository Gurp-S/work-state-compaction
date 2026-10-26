"""Two preregistered native forks; descriptive repeat variation, not WSC efficacy."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest, digest, import_evidence
from native_rollout_snapshot import capture_rollout
from native_fork_history import observe_fork_bytes
from native_execution_binding import verify_execution_binding
from native_continuity_checks import archive_workspace, aggregate
from native_pair_workspace import preserve_arm
from native_thread_archive import archive_threads
from native_runtime_probe import verify_runtime
from native_task_checks import require
from run_native_pair import NativeRPC, initialize, phase, SETTINGS, verify_pins
from strict_jsonl_study import STAGES, SECOND

OLD = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
AREA = Path('D:/agent-task-runs/wsc-native-repeat-20261023-v1')
GRADER = Path('D:/agent-task-runs/wsc-public-contract-calibration-20261023-v1/contract-checks.py')
METHODS = SECOND + ['NumericBoundaryAudit.test_large_signed_integer_value_and_hash',
                    'NumericBoundaryAudit.test_finite_extremes_and_all_unterminated_nonfinite_forms']
BUDGET = {'max_responses': 18, 'max_seconds': 420, 'max_total_tokens': 800000}


def prepare():
    AREA.mkdir()
    old = read(OLD / 'registration.json')
    source = read(OLD / 'source_task/acceptance/receipt.json')
    require(manifest(OLD / 'source-frozen') == source['source_manifest'], 'source_changed')
    frozen = AREA / 'frozen-workspace'
    shutil.copytree(OLD / 'source-frozen', frozen, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    contract = frozen / 'task-contract'
    contract.mkdir()
    shutil.copy2(GRADER, contract / 'checks.py')
    request = STAGES[1]['message'] + ' 本次验收原文位于task-contract/checks.py，当前具名范围位于task-contract/contract.json。'
    save(contract / 'contract.json', {'visibility': 'public_before_both_repeats_not_original_historical_source',
        'message': request, 'methods': METHODS, 'grader_sha256': file_hash(GRADER),
        'scope': 'Finite-number continuation including signed 4300/4301/5000 digit integers and finite extremes; line budget not requested'})
    shutil.copytree(frozen, AREA / 'workspace')
    initial = manifest(frozen)
    parent_binding = read('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1/history-binding.json')['binding']['parent']
    boundary = read(OLD / 'B/finite_task/phase-outcome.json')['usage_completion_evidence']['turn_id']
    live = Path(read(OLD / 'initial/B/thread-start.json')['thread']['path'])
    sources = [p for folder in ('src', 'experiments', 'tests') for p in (ROOT / folder).rglob('*.py')]
    pins = [*sources, Path(__file__), GRADER, Path(old['executable']), Path.home() / '.codex/config.toml',
            Path(parent_binding['path']), OLD / 'source_task/acceptance/receipt.json',
            ROOT / 'versions/20261023-fork-admission-v1-delta.zip']
    # Retain the actual portable task runtime, not merely the parent Python version.
    runtime = Path(old['runtime_command'][0])
    provenance = read(runtime.parent / 'provenance.json')
    for name, expected in provenance['runtime_sha256'].items():
        path = (runtime.parent / name).resolve()
        require(path.is_relative_to(runtime.parent) and file_hash(path) == expected, 'runtime_changed')
        pins.append(path)
    reg = {'purpose': 'continuity_task_diagnostic_not_comparison', 'origin': str(AREA),
        'workspace': str(AREA / 'workspace'), 'executable': old['executable'], 'model': old['model'],
        'effort': old['effort'], 'settings': SETTINGS, 'dynamic_tools': [], 'phase_budget': BUDGET,
        'initial_manifest': initial, 'protected_paths': old['protected_paths'] + [
            'task-contract/checks.py', 'task-contract/contract.json'],
        'shared_request': request, 'methods': METHODS, 'runtime_command': old['runtime_command'],
        'parent': parent_binding, 'before_turn_id': boundary,
        'source_live_path': str(live), 'source_live_sha256': file_hash(live),
        'original_workspace_manifest_sha256': digest(manifest(OLD / 'workspace')),
        'pins': {str(p.resolve()): file_hash(p) for p in pins},
        'registered_utc': datetime.now(timezone.utc).isoformat(),
        'runs': ['N1', 'N2'], 'archive_slots': {'N1': 'B', 'N2': 'C'},
        'archive_slot_note': 'Both slots are native forks; C is only the existing snapshot helper slot, not WSC',
        'stop': 'Infrastructure, unknown usage, source/config drift, protected changes, or cap stops later runs. Quality failures retained; no retries or cap extension.',
        'quality_policy': 'Named checks plus final artifact and report review; failures are observations, never repaired by parent',
        'cost_policy': 'Only new fork-local receipts are newly spent; historical parent cost reported separately, cash unknown',
        'limitations': ['Two observations are descriptive, not a variance estimate or temperature causal effect',
            'Both use native forks; no WSC strategy and no non-native transport contrast',
            'Published extended checks and new cwd differ from original B/C; do not pool raw results',
            'Fixed order, shared server/cache, hidden sampling parameters and service load are uncontrolled']}
    save(AREA / 'registration.json', reg)
    save(AREA / 'prepared.json', {'registration_sha256': file_hash(AREA / 'registration.json'),
                                 'model_calls': 0, 'source_manifest_sha256': digest(initial)})
    print(json.dumps({'prepared': str(AREA), 'runs': 2, 'budget_each': BUDGET, 'model_calls': 0}), flush=True)


def grade(reg, name):
    destination = AREA / name / 'acceptance'
    worker = "import sys,json;sys.path.insert(0,sys.argv[1]);from native_task_checks import grade;grade(sys.argv[2],sys.argv[3],json.loads(sys.argv[4]),sys.argv[5])"
    process = subprocess.run([*reg['runtime_command'], '-B', '-X', 'utf8', '-c', worker,
        str(ROOT / 'experiments'), reg['workspace'], str(Path(reg['workspace']) / 'task-contract/checks.py'),
        json.dumps(reg['methods']), str(destination)], capture_output=True, text=True, encoding='utf8', timeout=45)
    save(AREA / name / 'grade-worker.json', {'returncode': process.returncode, 'stdout': process.stdout,
        'stderr': process.stderr, 'runtime': reg['runtime_command'], 'model_calls': 0})
    require(process.returncode == 0, 'grader_infrastructure_failed')
    receipt = read(destination / 'receipt.json')
    require(receipt['tests'] == len(METHODS) and not receipt['skipped'], 'grader_scope_incomplete')
    require(file_hash(destination / 'fixture/tests/_task_grader.py') == file_hash(GRADER), 'grader_changed')
    return receipt


def run():
    reg = read(AREA / 'registration.json')
    require(file_hash(AREA / 'registration.json') == read(AREA / 'prepared.json')['registration_sha256'], 'registration_changed')
    verify_pins(reg)
    require(manifest(reg['workspace']) == reg['initial_manifest'], 'initial_changed')
    require(file_hash(reg['source_live_path']) == reg['source_live_sha256'], 'live_parent_changed')
    save(AREA / 'started.json', {'utc': datetime.now(timezone.utc).isoformat(), 'retry': False})
    opened, entries, outcomes, bindings = {}, {}, {}, {}
    result = {'status': 'started', 'entries': entries, 'cash': None, 'goal_complete': False}
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA / 'stderr.txt', settings=SETTINGS) as server:
            initialize(server)
            save(AREA / 'process.json', {'pid': server.proc.pid})
            runtime = verify_runtime(server, reg['workspace'], reg['runtime_command'], AREA / 'runtime-preflight')
            fact = {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': json.dumps({
                'kind': 'experimental_execution_binding', 'current_workspace': reg['workspace'],
                'current_file_manifest_sha256': digest(reg['initial_manifest']), 'execution_mode': 'workspace_write',
                'historical_workspace': str(OLD / 'workspace'),
                'source_history': 'Original native parent prefix; historical paths identify the earlier observation location.',
                'current_file_mapping': 'Registered source-stage file bytes at the same relative paths in current_workspace, with the public task contract added.',
                'task_runtime': runtime}, ensure_ascii=False, sort_keys=True)}]}
            save(AREA / 'execution-fact.json', fact)
            observations = {}
            for name in reg['runs']:
                cell = AREA / name
                cell.mkdir()
                response = server.call('thread/fork', {'threadId': reg['parent']['thread_id'],
                    'beforeTurnId': reg['before_turn_id'], 'model': reg['model'], 'cwd': reg['workspace'],
                    'approvalPolicy': 'never', 'sandbox': 'workspace-write', 'runtimeWorkspaceRoots': [reg['workspace']],
                    'ephemeral': False, 'excludeTurns': True, 'deferGoalContinuation': True}, timeout=45)
                opened[name] = response
                save(cell / 'thread-fork.json', response)
                server.call('thread/inject_items', {'threadId': response['thread']['id'], 'items': [fact]}, timeout=30)
                snapshot = capture_rollout(response['thread']['path'], archive=cell / 'before.jsonl')
                binding = {'child_sha256': snapshot.metadata['sha256'], 'parent': reg['parent']}
                bindings[name] = binding
                observation = observe_fork_bytes((cell / 'before.jsonl').read_bytes(), binding)
                require(not any(r['type'] == 'token_usage_record' for r in snapshot.rows), 'unregistered_inference')
                require(import_evidence(observation['items'][-1:], [fact])['matched'], 'execution_fact_missing')
                meta = next(r['payload'] for r in snapshot.rows if r['type'] == 'session_meta')
                normalized = deepcopy(observation['items'])
                # Exclude only native-generated message transport IDs/metadata.
                for item in normalized:
                    if item.get('type') == 'message':
                        item.pop('id', None)
                        item.pop('internal_chat_message_metadata_passthrough', None)
                config = {k: response.get(k) for k in ('model', 'modelProvider', 'reasoningEffort', 'cwd',
                    'sandbox', 'approvalPolicy', 'serviceTier', 'runtimeWorkspaceRoots')}
                require(config['model'] == reg['model'] and config['reasoningEffort'] == reg['effort']
                        and config['sandbox']['type'] == 'workspaceWrite' and config['approvalPolicy'] == 'never',
                        'runtime_configuration_changed')
                observations[name] = {'items': normalized, 'configuration': config,
                    'base_instructions': meta.get('base_instructions'), 'dynamic_tools': meta.get('dynamic_tools')}
                save(cell / 'history-binding.json', binding)
                save(cell / 'admission.json', {'history': observation['evidence'], 'configuration': config,
                    'control_sha256': digest(observations[name]), 'model_calls': 0})
            require(observations['N1'] == observations['N2'], 'paired_native_fork_controls_differ')
            save(AREA / 'paired-admission.json', {'equal': True, 'control_sha256': digest(observations['N1']),
                'model_calls': 0, 'scope': 'Saved effective history and observed native configuration, not wire-request proof'})
            for index, name in enumerate(reg['runs']):
                verify_pins(reg)
                require(manifest(reg['workspace']) == reg['initial_manifest'], 'repeat_start_changed')
                preg = {**reg, 'accounting_scope': 'fork_append_only_turn',
                        'fork_history_binding': bindings[name], 'execution_fact': fact}
                verify_execution_binding(preg, opened[name])
                cell = AREA / name
                save(cell / 'registration.json', preg)
                print(json.dumps({'status': 'running', 'run': name}), flush=True)
                outcome = phase(server, opened[name], preg, cell, None, time.monotonic() + BUDGET['max_seconds'])
                outcomes[name] = outcome
                after = archive_workspace(reg['workspace'], cell / 'after.zip')
                entries[name] = {'artifact': after, 'phase': str(cell / 'phase-outcome.json')}
                require(outcome['usage_complete'] and outcome['completed'] and not outcome['failure'], 'phase_stopped')
                require(len(outcome['finals']) == 1, 'final_missing')
                require(all(after['manifest'].get(p) == reg['initial_manifest'][p] for p in reg['protected_paths']), 'protected_changed')
                receipt = grade(reg, name)
                entries[name]['acceptance'] = {'passed': receipt['passed'], 'tests': receipt['tests'],
                    'receipt_sha256': file_hash(cell / 'acceptance/receipt.json')}
                save(cell / 'stage-result.json', entries[name])
                preserve_arm(AREA, reg['archive_slots'][name], AREA / 'frozen-workspace',
                             reg['initial_manifest'], restore_initial=index == 0)
                print(json.dumps({'status': 'run_finished', 'run': name, 'passed': receipt['passed']}), flush=True)
            result['status'] = 'two_native_repeats_executed_review_pending'
    except Exception as exc:
        result.update(status='stopped', error=type(exc).__name__ + ':' + str(exc))
    finally:
        result['threads'] = archive_threads(AREA, opened)
        result['usage'] = aggregate(list(outcomes.values()))
        result['source_live_unchanged'] = file_hash(reg['source_live_path']) == reg['source_live_sha256']
        result['original_workspace_unchanged'] = digest(manifest(OLD / 'workspace')) == reg['original_workspace_manifest_sha256']
        try:
            verify_pins(reg)
            archived = [r for v in result['threads'].values() for r in v['receipts']['response_receipts']]
            actual = [r for v in outcomes.values() for r in v['receipts']['response_receipts']]
            require(len(archived) == len({r['response_id'] for r in archived}), 'duplicate_archived_response')
            require({r['response_id']: r['usage'] for r in archived} == {r['response_id']: r['usage'] for r in actual}, 'unaccounted_response')
            require(result['source_live_unchanged'] and result['original_workspace_unchanged'], 'original_changed')
            result['archive_usage_verified'] = True
        except Exception as exc:
            result.update(status='stopped', accounting_error=str(exc))
        save(AREA / 'result.json', result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('threads', 'entries')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'run': run}[sys.argv[1]]()
