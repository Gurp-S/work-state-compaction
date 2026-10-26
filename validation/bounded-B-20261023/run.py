"""One registered native B continuation of the qualified bounded-command C task."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, manifest, digest, file_hash, records
from native_continuity_checks import aggregate, archive_workspace
from native_pair_admission import observe, CONFIG_FIELDS
from native_pair_workspace import preserve_arm
from native_runtime_probe import verify_runtime
from native_thread_archive import archive_threads
from native_task_checks import grade, require
from run_native_continuity import execution_item
from run_control_continuation import open_thread, require_completed, prior_fact
from run_native_pair import NativeRPC, SETTINGS, initialize, import_items, phase, verify_pins, audit_host
from prepare_bounded_command_study import STAGES
from wsc.contracts import encode

BASE = Path('D:/agent-task-runs/wsc-bounded-command-20261023-v2')
AREA = BASE / 'B'
COMPACT_BUDGET = dict(max_responses=1, max_seconds=180, max_total_tokens=250000)


def prepare():
    require(not AREA.exists(), 'B_already_registered')
    old = read(BASE / 'registration.json')
    review = read(BASE / 'reviewed-result.json')
    require(review['status'] == 'qualified_for_registered_single_boundary_task', 'C_not_qualified')
    source = read(BASE / 'source_task/stage-result.json')['after']
    final = read(BASE / 'handoff/stage-result.json')['after']
    require(manifest(old['workspace']) == final['manifest'], 'C_final_changed')
    require(file_hash(source['path']) == source['sha256'], 'source_archive_changed')
    AREA.mkdir()
    frozen = AREA / 'frozen-workspace'
    frozen.mkdir()
    with zipfile.ZipFile(source['path']) as z:
        require(len(z.namelist()) == len(set(z.namelist())), 'duplicate_archive_member')
        require({n: sha256(z.read(n)).hexdigest() for n in z.namelist()} == source['manifest'],
                'source_zip_manifest_changed')
        for name in z.namelist():
            path = (frozen / name).resolve()
            require(path.is_relative_to(frozen.resolve()), 'unsafe_source_member')
        z.extractall(frozen)
    require(manifest(frozen) == source['manifest'], 'frozen_source_changed')
    paths = [Path(p) for p in old['pins']] + [Path(__file__)]
    paths += [BASE / n for n in ('registration.json', 'reviewed-result.json',
        'source_task/stage-result.json', 'source_task/phase-outcome.json', 'source_task/rollout.jsonl',
        'source_task/thread-start.json', 'source_task/admission.json',
        'source_task/registration.json', 'source_task/acceptance/receipt.json',
        'source_task/after.zip', 'expanded_task/registration.json',
        'expanded_task/host-observation/admission.json', 'handoff/stage-result.json')]
    changed = [p for p,h in old['pins'].items() if file_hash(p) != h]
    expected = {str((ROOT/'experiments/run_native_pair.py').resolve()),
                str((ROOT/'tests/test_native_phase_budget.py').resolve())}
    require(set(changed) == expected, 'unreviewed_source_drift')
    reg = {**old, 'purpose': 'comparison', 'origin': str(AREA),
        'registered_utc': datetime.now(timezone.utc).isoformat(),
        'initial_manifest': source['manifest'], 'C_final_manifest': final['manifest'],
        'pins': {str(p.resolve()): file_hash(p) for p in paths},
        'stages': STAGES[1:], 'compaction_budget': COMPACT_BUDGET,
        'candidate': {'kind': 'unchanged_native_compaction_then_original_thread_continuation'},
        'limits': {'retries': 0, 'forced_compactions': 1},
        'scope': 'One fixed-order paired task, same source thread/history/cwd and source-stage file bytes. Not long-horizon proof.',
        'boundary_fact': 'The exact C expanded execution fact is injected before native compaction and again before the expanded turn; it carries the shared source receipt and runtime facts. Native prompts/configuration unchanged.',
        'accounting': 'Only new response IDs in compaction/expanded/handoff. Shared source cost is reported separately. Unknown remains unknown.',
        'known_harness_delta_after_C': changed,
        'stop': 'Any failed phase, incomplete usage, missing final, changed protected file or failed acceptance ends this attempt. No retry or cap extension.'}
    save(AREA/'registration.json', reg)
    verify_pins(reg)
    save(AREA/'prepared.json', {'registration_sha256':file_hash(AREA/'registration.json'), 'model_calls':0})
    print(json.dumps({'prepared':str(AREA), 'model_calls':0}), flush=True)


def run():
    reg = read(AREA/'registration.json')
    require(file_hash(AREA/'registration.json') == read(AREA/'prepared.json')['registration_sha256'], 'registration_changed')
    verify_pins(reg)
    require(manifest(reg['workspace']) == reg['C_final_manifest'], 'C_final_changed')
    save(AREA/'started.json', {'utc':datetime.now(timezone.utc).isoformat(), 'retry':False})
    opened, phases, entries = {}, [], []
    result = {'status':'started', 'stages':entries, 'cash':None}
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA/'stderr.txt', settings=SETTINGS) as server:
            initialize(server)
            runtime = verify_runtime(server, reg['workspace'], reg['runtime_command'], AREA/'runtime-preflight')
            plugins = server.call('plugin/list', {'cwds':[reg['workspace']], 'forceRefetch':False}, timeout=45)
            skills = server.call('skills/list', {'cwds':[reg['workspace']], 'forceReload':False}, timeout=45)
            save(AREA/'discovery.json', {'plugins':plugins, 'skills':skills})
            require(not plugins.get('marketplaceLoadErrors'), 'plugin_discovery_failed')
            # Fresh host observation must use the same initialization sequence as C.
            cell = AREA/'host-observation'; cell.mkdir()
            probe = open_thread(server, reg, cell); opened['host_probe'] = probe
            marker = [{'type':'message', 'role':'assistant', 'phase':'commentary', 'content':[
                {'type':'output_text', 'text':'{"kind":"host_observation","task_execution":"not_started"}'}]}]
            import_items(server, probe, marker, cell)
            admission = observe(probe, marker); save(cell/'admission.json', admission)
            expected = read(BASE/'expanded_task/host-observation/admission.json')['host']
            require(admission['host'] == expected and admission['response_count'] == 0, 'current_host_changed')
            source = read(BASE/'source_task/thread-start.json')
            source_phase = read(BASE/'source_task/phase-outcome.json')
            require(file_hash(source['thread']['path']) == source_phase['rollout_sha256'], 'source_history_changed')
            fact = read(BASE/'expanded_task/registration.json')['execution_fact']
            require(json.loads(fact['content'][0]['text'])['task_runtime'] == runtime, 'runtime_changed')
            # Preserve C and restore only within the checked study workspace.
            save(AREA/'workspace-restore.json', preserve_arm(BASE, 'C', AREA/'frozen-workspace',
                 reg['initial_manifest'], restore_initial=True))
            value = server.call('thread/resume', {'threadId':source['thread']['id'],
                'cwd':reg['workspace'], 'model':reg['model'], 'approvalPolicy':'never',
                'sandbox':'workspace-write', 'excludeTurns':True}, timeout=40)
            opened['B'] = value; save(AREA/'thread-resume.json', value)
            require(Path(value['thread']['path']).samefile(source['thread']['path']), 'resume_wrong_rollout')
            require({k:value.get(k) for k in CONFIG_FIELDS} == expected['native_configuration'], 'resume_configuration_changed')
            original = (BASE/'source_task/rollout.jsonl').read_bytes()
            require(Path(value['thread']['path']).read_bytes().startswith(original), 'resume_source_prefix_changed')
            current = reg['initial_manifest']
            prior = prior_fact(read(BASE/'source_task/acceptance/receipt.json'), BASE/'source_task/acceptance/receipt.json')
            for stage in [{'id':'compaction', 'budget':reg['compaction_budget'], 'message':'', 'methods':None}, *reg['stages']]:
                cell = AREA/stage['id']; cell.mkdir()
                require(manifest(reg['workspace']) == current, 'interstage_workspace_changed')
                before = archive_workspace(reg['workspace'], cell/'before.zip')
                if stage['id'] == 'handoff':
                    fact = execution_item(reg['workspace'], stage, current, prior)
                    fact['content'][0]['text'] = encode({**json.loads(fact['content'][0]['text']), 'task_runtime':runtime})
                import_items(server, value, [fact], cell)
                phase_reg = {**reg, 'execution_fact':fact, 'shared_request':stage['message'],
                    'accounting_scope':'append_only_turn', 'phase_budget':stage['budget']}
                save(cell/'registration.json', phase_reg)
                compact = stage['id'] == 'compaction'
                outcome = phase(server, value, phase_reg, cell, None,
                                time.monotonic()+stage['budget']['max_seconds'], compact=compact)
                phases.append(outcome)
                after = archive_workspace(reg['workspace'], cell/'after.zip')
                entry = {'stage_id':stage['id'], 'before':before, 'after':after}; entries.append(entry)
                require_completed(outcome)
                require(compact or len(outcome['finals']) == 1, 'final_delivery_missing')
                audit_host(cell)
                require(all(after['manifest'].get(p) == reg['initial_manifest'][p] for p in reg['protected_paths']), 'protected_file_changed')
                current = after['manifest']
                if stage['methods']:
                    receipt = grade(reg['workspace'], reg['grader'], stage['methods'], cell/'acceptance')
                    prior = prior_fact(receipt, cell/'acceptance/receipt.json'); entry['acceptance'] = prior
                    require(receipt['passed'], 'acceptance_failed')
                else:
                    require(current == before['manifest'], 'nonediting_stage_changed_workspace')
                save(cell/'stage-result.json', entry)
            result['status'] = 'B_executed_semantic_review_pending'
    except Exception as exc:
        result.update(status='stopped', error=type(exc).__name__+':'+str(exc))
    finally:
        result['threads'] = archive_threads(AREA, opened)
        try:
            result['usage'] = aggregate(phases)
            all_receipts = [r for t in result['threads'].values() for r in t.get('receipts',{}).get('response_receipts',[])]
            historical = read(BASE/'source_task/phase-outcome.json')['receipts']['response_receipts']
            old_ids = {r['response_id'] for r in historical}
            new = [r for r in all_receipts if r['response_id'] not in old_ids]
            require({r['response_id'] for r in new} == set(result['usage']['response_ids']), 'unaccounted_new_response')
            phase_receipts = [r for p in phases for r in p.get('receipts',{}).get('response_receipts',[])]
            require({r['response_id']:r['usage'] for r in new} == {r['response_id']:r['usage'] for r in phase_receipts}, 'archive_usage_changed')
            result['archive_usage_verified'] = True
        except Exception as exc:
            result.update(status='stopped', accounting_error=str(exc))
        result['historical_shared_source_usage'] = read(BASE/'source_task/phase-outcome.json')['receipts']['all_usage']
        result['goal_complete'] = False
        save(AREA/'result.json', result)
        print(json.dumps({k:v for k,v in result.items() if k not in {'threads','stages'}},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    {'prepare':prepare, 'run':run}[sys.argv[1]]()
