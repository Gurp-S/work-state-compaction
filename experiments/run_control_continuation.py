"""Registered source task -> automatic WSC checkpoint -> expanded task -> handoff.

One new task qualification attempt. No native B arm, retries, or HostReceipt.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import time

from native_continuity_checks import aggregate, archive_workspace
from native_evidence import digest, file_hash, manifest, read, save
from native_pair_admission import observe
from native_runtime_probe import verify_runtime
from native_task_checks import grade, require
from native_task_checkpoint import generate_checkpoint
from native_receipt_identity import receipt_reference
from native_message_checkpoint import prepare_message_checkpoint
from native_host_checkpoint import PendingHostCheckpoint
from native_thread_archive import archive_threads
from run_native_continuity import execution_item
from run_native_pair import MODEL, SETTINGS, NativeRPC, audit_host, audit_import, import_items, initialize, phase, verify_pins
from run_quote_selection_probe import SchemaServer
from wsc.contracts import encode

HERE = Path(__file__).resolve().parent
METHODS = ['ControlRetentionTests.' + n for n in (
    'test_empty_selection_retains_declared_control_exactly_and_exports_it',
    'test_all_declared_control_roles_and_kinds_share_the_same_retention_rule',
    'test_mandatory_floor_rejects_before_generator_and_ignores_forged_snapshot_fields',
    'test_exact_floor_and_selection_facts_match_actual_retention',
    'test_control_access_denial_cannot_be_bypassed_by_empty_selection',
    'test_retained_control_survives_frontier_and_new_control_invalidates_old_snapshot',
    'test_opaque_control_is_rejected_before_generator_but_unmarked_opaque_stays_cold')]
STAGES = [
    {'id': 'source_task', 'message': '修复这个独立 WSC 库的非 opaque 控制记录遗漏：宿主给事件显式设置 control=True，但未设置 role 时，空 Selection 生成的视图会漏掉它。当前阶段处理可公开的事件：显式 control 与既有 user/system/developer 角色的失效、保留和预算规则一致，原角色、顺序、时间、载荷不变，普通观察仍可省略；预算不可容纳时在调用生成器前拒绝，权限限制仍有效，增量生成保留相同记录。只有 kind 标签而没有控制标记/角色不自动升级为控制。opaque 的扩展要求留到下一阶段。请修复并完成必要检查，说明结果及边界。', 'methods': METHODS[:6]},
    {'id': 'expanded_task', 'message': '继续同一 WSC 修复，现将验收范围扩大到 opaque：显式 control=True 的 opaque 记录无法作为公开热内容保留时，generate 应在调用生成器和创建用量尝试之前拒绝；不带控制标记的普通 opaque 仍能留在冷层，已有可公开控制与普通记录行为保持。请完成这个新增要求，验证当前版本并交代实际范围。', 'methods': METHODS},
    {'id': 'handoff', 'message': '请依据当前工作区与已取得的证据完成最终交接：说明当前实现、实际验证范围、已知兼容边界和仍未覆盖的部分。', 'methods': None},
]


def prepare(area, executable, runtime=None):
    require(not area.exists(), 'control_study_already_exists')
    old = Path('D:/agent-task-runs/wsc-control-retention-20261023-v1')
    original = read(old / 'registration.json')['source_before']
    before = {p: h for p, h in manifest(old / 'baseline/src').items() if p.endswith('.py')}
    require(before == {p[4:]: h for p, h in original.items() if p.startswith('src/')},
            'control_original_source_changed')
    area.mkdir()
    frozen = area / 'frozen-workspace'
    # The original delivery binds Python source, not local packaging metadata.
    for relative in before:
        target = frozen / 'src' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old / 'baseline/src' / relative, target)
    (frozen / 'tests').mkdir()
    for name in ('test_generation_feasibility.py', 'test_selection_facts.py', 'test_generation_frontier.py'):
        source = old / 'baseline/tests' / name
        require(file_hash(source) == original['tests/' + name], 'control_existing_check_changed')
        shutil.copy2(source, frozen / 'tests' / name)
    shutil.copy2(HERE.parents[1] / 'AGENTS.md', frozen / 'AGENTS.md')
    shutil.copytree(frozen, area / 'workspace')
    grader = HERE.parent / 'tests/test_control_retention.py'
    pins = [executable, grader, HERE.parents[1] / 'AGENTS.md', old / 'registration.json']
    runtime_command = ['py', '-3.11']
    if runtime is not None:
        runtime = Path(runtime).resolve()
        provenance = runtime.parent / 'provenance.json'
        for name, expected in read(provenance)['runtime_sha256'].items():
            path = (runtime.parent / name).resolve()
            require(path.is_relative_to(runtime.parent) and file_hash(path) == expected, 'task_runtime_changed')
            pins.append(path)
        pins.append(provenance)
        runtime_command = [str(runtime)]
    pins.extend(p for folder in ('src', 'tests', 'experiments') for p in (HERE.parent / folder).rglob('*.py'))
    config = Path.home() / '.codex/config.toml'
    if config.exists():
        pins.append(config)
    reg = {'purpose': 'C_task_qualification_only', 'registered_utc': datetime.now(timezone.utc).isoformat(),
        'origin': str(area), 'workspace': str(area / 'workspace'), 'executable': str(executable),
        'model': MODEL, 'effort': 'max', 'settings': SETTINGS, 'dynamic_tools': [],
        'initial_manifest': manifest(frozen), 'grader': str(grader), 'stages': STAGES,
        'runtime_command': runtime_command, 'protected_paths': ['AGENTS.md'],
        'pins': {str(p.resolve()): file_hash(p) for p in pins},
        'limits': {'task_responses_per_stage': 10, 'task_seconds_per_stage': 480,
                   'generation_responses': 4, 'generation_seconds': 180, 'handoff_seconds': 180,
                   'generation_material_bytes': 524288, 'view_bytes': 262144,
                   'retries': 0, 'B_calls': 0, 'forced_compactions': 0},
        'candidate': {'selection': 'automatic_word_span_first_checkpoint', 'schema': 'enumerated',
                      'presentation': 'recorded_covered', 'scope_observation': True},
        'scope': 'New staged real-code task with registered requests; no claim of default native compaction comparison.',
        'stop': 'Failure, unknown usage, changed protected file or cap stops later phases. No restart or cap extension.'}
    save(area / 'registration.json', reg)
    baseline = grade(area / 'workspace', grader, METHODS, area / 'baseline-acceptance')
    require(baseline['tests'] == 7 and len(baseline['failures']) == 7 and not baseline['errors'],
            'control_baseline_diagnostic_changed')
    print(encode({'prepared': str(area), 'baseline_failures': 7, 'model_calls': 0}), flush=True)


def open_thread(server, reg, cell, *, read_only=False):
    opened = server.call('thread/start', {'cwd': reg['workspace'], 'model': MODEL,
        'allowProviderModelFallback': False, 'approvalPolicy': 'never',
        'sandbox': 'read-only' if read_only else 'workspace-write',
        'runtimeWorkspaceRoots': [reg['workspace']], 'ephemeral': False, 'dynamicTools': []}, timeout=40)
    save(cell / 'thread-start.json', opened)
    require(opened['model'] == MODEL and opened.get('reasoningEffort') == 'max' and
            opened['sandbox']['type'] == ('readOnly' if read_only else 'workspaceWrite') and
            opened['approvalPolicy'] == 'never', 'control_native_configuration_changed')
    return opened


def require_completed(outcome):
    require(outcome['completed'] and not outcome['failure'] and outcome.get('usage_complete'),
            'control_phase_incomplete')


def prior_fact(receipt, path, *, bind_receipt_file=False):
    reference = (receipt_reference(receipt, path) if bind_receipt_file else
                 {'receipt_path': str(path), 'receipt_sha256': digest(receipt)})
    return {k: receipt[k] for k in ('source_manifest_sha256', 'names', 'tests', 'passed', 'grader_sha256')} | reference


def checkpoint_phase(server, reg, area, opened, phases, current, source_phase, source_rollout, receipt, receipt_path):
    mode = reg.get('candidate', {}).get('checkpoint_mode', 'generated')
    require(mode in {'generated', 'messages', 'host_messages'}, 'checkpoint_mode_invalid')
    if mode == 'host_messages':
        source_cell = (Path(reg['source_recovery']['phase']).parent if reg.get('source_recovery')
                       else area / 'source_task')
        return PendingHostCheckpoint(area / 'checkpoint', reg['workspace'], source_rollout,
                                     source_phase, receipt, receipt_path, source_cell)
    if mode == 'messages':
        return prepare_message_checkpoint(area / 'checkpoint', reg['workspace'], source_rollout,
                                          source_phase, receipt, receipt_path)
    gen_cell = area / 'generation'
    gen_cell.mkdir()
    generator = open_thread(server, reg, gen_cell, read_only=True)
    opened['generator'] = generator
    def execute(request, schema):
        verify_pins(reg)
        generation_reg = {**reg, 'purpose': 'automatic_selection_generation_only',
                          'shared_request': encode(request), 'accounting_scope': 'fresh_single_turn'}
        save(gen_cell / 'registration.json', generation_reg)
        out = phase(SchemaServer(server, schema), generator, generation_reg, gen_cell, None,
                    time.monotonic() + 180, spent_responses=6)
        phases.append(out)
        require(manifest(reg['workspace']) == current, 'control_generator_changed_workspace')
        audit_host(gen_cell)
        return out, gen_cell / 'rollout.jsonl'
    return generate_checkpoint(area / 'checkpoint', reg['workspace'], source_rollout,
                               source_phase, receipt, receipt_path, execute)


def run(area, *, stages=None):
    reg = read(area / 'registration.json')
    verify_pins(reg)
    recovery = reg.get('source_recovery')
    expected_stages = STAGES if stages is None else stages
    require(reg['stages'] == (expected_stages[1:] if recovery else expected_stages)
            and manifest(reg['workspace']) == reg['initial_manifest'],
            'control_registration_or_initial_source_changed')
    save(area / 'started.json', {'utc': datetime.now(timezone.utc).isoformat(), 'retry': False})
    opened, phases, entries = {}, [], []
    result = {'status': 'started', 'stages': entries, 'cash': None}
    prior, current = None, reg['initial_manifest']
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=area / 'stderr.txt', settings=SETTINGS) as server:
            save(area / 'initialize.json', initialize(server))
            runtime_fact = verify_runtime(server, reg['workspace'], reg.get('runtime_command', ['py', '-3.11']),
                                          area / 'runtime-preflight')
            plugins = server.call('plugin/list', {'cwds': [reg['workspace']], 'forceRefetch': False}, timeout=45)
            skills = server.call('skills/list', {'cwds': [reg['workspace']], 'forceReload': False}, timeout=45)
            save(area / 'discovery.json', {'plugins': plugins, 'skills': skills})
            require(not plugins.get('marketplaceLoadErrors'), 'control_plugin_discovery_failed')
            package = None
            if recovery:
                receipt = read(recovery['acceptance'])
                prior = prior_fact(receipt, recovery['acceptance'])
                result['historical_source_usage'] = read(recovery['original_result'])['usage']
                package = checkpoint_phase(server, reg, area, opened, phases, current,
                    read(recovery['phase']), recovery['rollout'], receipt, recovery['acceptance'])
            for index, stage in enumerate(reg['stages']):
                verify_pins(reg)
                cell = area / stage['id']
                cell.mkdir()
                require(manifest(reg['workspace']) == current, 'control_interstage_workspace_changed')
                before = archive_workspace(reg['workspace'], cell / 'before.zip')
                if stage['id'] != 'handoff':
                    value = open_thread(server, reg, cell)
                    opened['source' if stage['id'] == 'source_task' else 'C'] = value
                else:
                    value = opened['C']
                fact = execution_item(reg['workspace'], stage, current, prior)
                fact_value = json.loads(fact['content'][0]['text'])
                fact['content'][0]['text'] = encode({**fact_value, 'task_runtime': runtime_fact})
                if stage['id'] == 'expanded_task' and isinstance(package, PendingHostCheckpoint):
                    items = package.import_into(server, value, cell, fact)
                else:
                    items = ([*package['items'], fact] if stage['id'] == 'expanded_task' else [fact])
                    import_items(server, value, items, cell)
                if stage['id'] != 'handoff':
                    admission = observe(value, items)
                    save(cell / 'admission.json', admission)
                    require(admission['response_count'] == 0, 'control_unregistered_prior_inference')
                phase_reg = {**reg, 'purpose': 'continuity_task_diagnostic_not_comparison',
                    'execution_fact': fact, 'shared_request': stage['message'],
                    'accounting_scope': 'append_only_turn' if stage['id'] == 'handoff' else 'fresh_single_turn'}
                if 'budget' in stage:
                    phase_reg['phase_budget'] = stage['budget']
                save(cell / 'registration.json', phase_reg)
                wall_seconds = stage.get('budget', {}).get('max_seconds',
                                                           180 if stage['id'] == 'handoff' else 480)
                outcome = phase(server, value, phase_reg, cell, None,
                                time.monotonic() + wall_seconds)
                phases.append(outcome)
                after = archive_workspace(reg['workspace'], cell / 'after.zip')
                entry = {'stage_id': stage['id'], 'before': before, 'after': after}
                entries.append(entry)
                require_completed(outcome)
                if reg.get('require_final'):
                    require(len(outcome['finals']) == 1, 'task_final_delivery_missing')
                audit_host(cell)
                audit_import(cell, items)
                require(all(after['manifest'].get(p) == reg['initial_manifest'][p]
                            for p in reg.get('protected_paths', ['AGENTS.md'])), 'control_protected_input_changed')
                current = after['manifest']
                if stage['methods']:
                    receipt = grade(reg['workspace'], reg['grader'], stage['methods'], cell / 'acceptance')
                    prior = prior_fact(receipt, cell / 'acceptance/receipt.json')
                    entry['acceptance'] = prior
                    require(receipt['passed'], 'control_acceptance_failed')
                else:
                    require(current == before['manifest'], 'control_handoff_changed_workspace')
                    entry['acceptance'] = {'carried_receipt': prior, 'semantic_review': 'pending'}
                save(cell / 'stage-result.json', entry)
                if stage['id'] == 'source_task':
                    package = checkpoint_phase(server, reg, area, opened, phases, current,
                        outcome, cell / 'rollout.jsonl', receipt, cell / 'acceptance/receipt.json')
            result['status'] = 'C_task_executed_semantic_review_pending'
    except Exception as exc:
        result.update(status='stopped', error=type(exc).__name__ + ':' + str(exc))
    finally:
        result['threads'] = archive_threads(area, opened)
        try:
            result['usage'] = aggregate(phases)
            archived = [r for t in result['threads'].values() for r in t.get('receipts', {}).get('response_receipts', [])]
            archived_ids = [r['response_id'] for r in archived]
            require(len(archived_ids) == len(set(archived_ids)) and
                    sorted(archived_ids) == result['usage']['response_ids'] and
                    all(sum(r['usage'][field] for r in archived) == amount
                        for field, amount in result['usage']['known_usage'].items()) and
                    not any(t.get('accounting_error') for t in result['threads'].values()),
                    'control_final_archive_usage_mismatch')
            result['archive_matches_phase_usage'] = True
        except Exception as exc:
            if 'usage' in result:
                result['usage'].update(complete=False, complete_usage=None)
            result.update(status='stopped', accounting_error=str(exc))
        save(area / 'result.json', result)
    print(encode({'status': result['status'], 'error': result.get('error'), 'usage': result.get('usage')}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('prepare', 'run'))
    p.add_argument('area', type=Path)
    p.add_argument('--executable', type=Path)
    p.add_argument('--runtime', type=Path)
    args = p.parse_args()
    if args.action == 'prepare':
        prepare(args.area.resolve(), args.executable.resolve(), args.runtime)
    else:
        run(args.area.resolve())
