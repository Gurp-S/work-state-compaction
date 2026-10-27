"""Three preregistered paired continuations; two physical private workspaces."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Barrier
import json
import math
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,digest,usage
from native_study_fork_session import NativeForkSession
from native_application_capability import admit
from native_application_budget import StudyBudget
from native_application_adapters import FrozenApplicationAdapters
from native_fixture_transport import public_binding
from native_rollout_snapshot import capture_rollout
from native_campaign_envelope import qualification_envelope
from native_s2_workspace_restore import restore
from native_stage_time_policy import propose
import native_cold_access
from native_package_media import dependencies as package_media_dependencies
from native_repeat_admission import decide as repeat_admission
from native_execution_time import carry as carry_execution_time

OUT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
SEED=OUT/'B-seed-v2'
RUN=OUT/'execution-v3'
RUN.mkdir(exist_ok=False)
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
FROZEN=COMMON/'staged/frozen-workspace'
spec=read(OUT/'registration.json')
seed=read(SEED/'result.json')
assert seed['completed'] and seed['usage_complete'] and seed['source_unchanged'] and seed['cleanup']['empty_confirmed']
assert not seed['ledger']['inflight'] and not seed['ledger']['study']['uncertain']
assert file_hash(Path(seed['rollout_path']))==seed['native_source_sha256']
source_reg=read(COMMON/'registration.json')
conditions=propose({**source_reg['conditions'],'fixture_transport':'http_attached_websocket_v1',
    'evaluation_host':'a3_production_panel_host_v1','indexed_checkpoint':True,'phase_budget_facts':True,'standalone_stage':3})
limits=spec['per_arm_limits']
prior_envelope=OUT/'execution-v2/R03/next-admission-envelope.json'
adoption=read(OUT/'execution-time-policy-adoption.json')
assert adoption['user_choice']=='按实际实验运行时间累计，额度等待不计（推荐）'
assert adoption['parent_envelope_sha256']==file_hash(prior_envelope)
envelope=carry_execution_time(read(prior_envelope),adoption['new_completed_operation_seconds'])
quota=read(Path(adoption['quota_readback']))
assert quota['available_observed'] and quota['cleanup']['empty_confirmed'],'current_quota_not_admitted'
DIAGNOSTIC=Path(adoption['scope_diagnostic_path'])
code_pins={str(path):file_hash(path) for folder in ('src','experiments') for path in (ROOT/folder).rglob('*.py')}
for path in (Path(__file__),Path(__file__).with_name('grade_auto_compacting_c_s3.py'),OUT/'registration.json',
             OUT/'C-package.json',OUT/'shared-raw-observations.json',SEED/'result.json',
             Path(__file__).with_name('s3-concurrency-direct.mjs'),Path(__file__).with_name('s3-scope-check.mjs'),
             Path(__file__).with_name('check_s2_clipping.mjs'),DIAGNOSTIC,OUT/'execution-time-policy-adoption.json'):
    code_pins[str(path)]=file_hash(path)
save(RUN/'execution-contract.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),conditions=conditions,
    fixed_seed_comparison=True,repetitions=2,remaining_registered_repetitions=[2,3],concurrent_arms=2,native_B_default_unchanged=True,
    initial_envelope=envelope,pins=code_pins,per_arm_limits=limits,automatic_retries=0,
    repetition_budget_policy='Separately registered closed pairs; next envelope uses existing conservative qualification_envelope. No old uncertain ledger resumed; unused allocation withheld, not labelled actual spend.',
    future_pair_gate='Previous pair processes closed, no inflight tickets, exact S2 restore, frozen seed and implementation pins unchanged',
    outcome_policy='Every started arm retained; incomplete native execution is failure even if UI checks pass; unknown cost remains unknown',
    setup_costs=dict(B_native_seed_tokens=seed['ledger']['study']['tokens'],B_seed_complete=True,
        C_latest_incremental_selection_tokens=76397,C_full_historical_material_preparation_cost=None,
        setup_expense_not_zero=True),
    inference_scope='Continuation variability conditional on these two fixed seed states; excludes compression-generation variability and full five-task matrix',
    attribution_scope='C combination vs native-default B; timing versus semantic contribution unresolved'))
(RUN/'cohort-controller.py').write_bytes(Path(__file__).read_bytes())

def unchanged():
    assert all(file_hash(Path(path))==value for path,value in code_pins.items()), 'cohort_implementation_or_seed_changed'

def run_arm(arm,repeat,area,budget,gate):
    reg=dict(spec['sessions'][arm])
    if arm=='B':
        reg['parent_thread_id']=seed['thread_id']
        reg['parent_paths']={**reg['parent_paths'],seed['thread_id']:seed['rollout_path']}
    session=NativeForkSession(reg,area/'receiver')
    save(area/'prepared.json',dict(registration=reg,request=spec['request'],package=str(OUT/'C-package.json') if arm=='C' else None))
    result=dict(arm=arm,repeat=repeat,inference_started=False)
    phases=[]
    ticket=None
    arm_key=f'R{repeat:02d}/{arm}'
    try:
        unchanged()
        session.open()
        if arm=='B':
            assert any(p['thread_id']==seed['thread_id'] and p['prefix_sha256']==seed['native_source_sha256']
                for p in session.fork_binding['parents']), 'B_fixed_seed_changed'
        admit(session,area/'browser-capability')
        if arm=='C':
            package=read(OUT/'C-package.json')
            session.inject(package['items'])
            media=package_media_dependencies(package)
            native_cold_access.package(session,package,area/'cold-access',media)
        gate.wait(timeout=120)
        ticket,granted=budget.reserve(arm_key,limits)
        save(area/'grant.json',dict(ticket=ticket,limits=granted))
        facts=dict(kind='native_development_execution_state',stage='S3',current_workspace=reg['workspace'],
            business_manifest_sha256=digest(reg['initial_manifest']),phase_budget=granted,
            phase_deadline_utc=(datetime.now(timezone.utc)+timedelta(seconds=granted['max_seconds'])).isoformat(),
            allocated_local_ports=[29510,29511,29512] if arm=='B' else [29520,29521,29522],
            public_acceptance_helper_module=str(Path(reg['fixture_root'])/'harness/acceptance-cases.mjs'),**public_binding(reg))
        save(area/'runtime-facts.json',facts)
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[dict(type='message',role='developer',
            content=[dict(type='input_text',text=json.dumps(facts,ensure_ascii=False))])]))
        gate.wait(timeout=120) # Both arm grants and execution facts exist before either request.
        def record(phase):
            phases.append(phase);save(area/'phase-journal.json',phase)
            save(area/'settlement.json',budget.settle(ticket,phase))
        print(arm_key+' running',flush=True)
        result['inference_started']=True
        phase=session.execute_stage(spec['request'],area/'S3-phase',granted,record)
        result.update(native_completed=phase['completed'],usage_complete=phase['usage_complete'],failure=phase['failure'])
    except Exception as error:
        result['error']=type(error).__name__+':'+str(error)
        gate.abort()
    finally:
        result['cleanup']=session.close()
        if session.opened:
            snap=capture_rollout(session.opened['thread']['path'],archive=area/'closed-native.jsonl')
            expected={r['response_id']:r['usage'] for p in phases for r in p.get('receipts',{}).get('response_receipts',[])}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            late=[r for r in snap.rows if r['type']=='token_usage_record' and r['payload']['response_id'] not in expected]
            if ticket and not phases:
                # A reserved but unjournalled attempt is unknown, including a
                # turn/start reply loss; never drop its ticket or observed cost.
                receipts=usage(snap.rows,session.opened['thread']['id'])
                budget.settle(ticket,dict(receipts=receipts,usage_complete=False))
            elif actual!=expected or not snap.metadata['parse_complete']:
                budget.mark_unknown(arm_key,usage(late,session.opened['thread']['id'])['response_receipts'] if late else ())
                result['accounting_mismatch']=True
        elif ticket:
            budget.settle(ticket,dict(receipts={},usage_complete=False))
        result['source_manifest_after']=session.source_manifest()
        result['pins_unchanged']=all(file_hash(Path(path))==value for path,value in code_pins.items())
        result['whole_campaign_usage_complete']=False
        save(area/'result.json',result)
    return result

def grade(arm,area,result):
    grade_result=dict(arm=arm,model_calls=0)
    if not result['inference_started']:
        grade_result.update(qualification_passed=False,reason='infrastructure_preflight_not_executed')
        save(area/'qualification.json',grade_result);return grade_result
    reg=read(area/'prepared.json')['registration']
    job=json.loads(json.dumps(next(job for job in source_reg['jobs'] if job['arm']==arm)))
    job['resources'].update(workspace=reg['workspace'],output=str(area))
    try:
        adapter=FrozenApplicationAdapters(conditions,source_reg['tasks'],source_reg['expected_checks'],node_executable=source_reg['node_executable'])
        automatic=adapter.grade(job,3,area/'S3-acceptance')
        save(area/'S3-grade.json',automatic)
        with (area/'supplemental-stdout.txt').open('x',encoding='utf-8') as stdout,(area/'supplemental-stderr.txt').open('x',encoding='utf-8') as stderr:
            completed=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).with_name('grade_auto_compacting_c_s3.py')),str(area),str(DIAGNOSTIC)],
                stdout=stdout,stderr=stderr,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        assert completed.returncode==0,'supplemental_driver_failed'
        supplemental=read(area/'supplemental-grade.json')
        ui=all(r['passed'] for r in automatic['observations']) and supplemental['concurrency']['passed'] and supplemental['scope']['passed']
        ui=ui and not supplemental['clipping']['clipping_observed'] and supplemental['source_unchanged']
        passed=(ui and result.get('native_completed') is True and result.get('usage_complete') is True and not result.get('failure')
            and not result.get('error') and not result.get('accounting_mismatch') and result['pins_unchanged'] and result['cleanup']['empty_confirmed'])
        grade_result.update(qualification_passed=passed,functional_17_and_scroll=ui)
        grade_result['scoped_control_diagnostic_passed']=read(area/'scope-diagnostic-grade.json')['passed']
    except Exception as error:
        grade_result.update(qualification_passed=False,error=type(error).__name__+':'+str(error))
    save(area/'qualification.json',grade_result)
    return grade_result

all_pairs=[]
for repeat in (2,3):
    unchanged()
    pair=RUN/f'R{repeat:02d}'
    pair.mkdir(exist_ok=False)
    start=time.monotonic()
    budget=StudyBudget({f'R{repeat:02d}/{arm}':limits for arm in ('B','C')},envelope['remaining_limits'])
    gate=Barrier(2)
    save(pair/'registration.json',dict(repeat=repeat,cohort_sha256=file_hash(OUT/'registration.json'),
        execution_contract_sha256=file_hash(RUN/'execution-contract.json'),envelope=envelope,arm_limits=limits))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={arm:pool.submit(run_arm,arm,repeat,pair/arm,budget,gate) for arm in ('B','C')}
        results={arm:future.result() for arm,future in futures.items()}
    grades={arm:grade(arm,pair/arm,results[arm]) for arm in ('B','C')}
    snapshot=budget.snapshot()
    assert not snapshot['inflight'],'closed_pair_has_inflight_ticket'
    assert all(r['cleanup']['empty_confirmed'] for r in results.values()),'pair_processes_not_closed'
    receipt=dict(repeat=repeat,results=results,grades=grades,ledger=snapshot,seconds=time.monotonic()-start,
        whole_campaign_usage_complete=False)
    save(pair/'pair-result.json',receipt)
    all_pairs.append(dict(repeat=repeat,result_sha256=file_hash(pair/'pair-result.json'),grades=grades))
    envelope=qualification_envelope(snapshot,[],receipt['seconds'])
    envelope.update(old_unknowns_preserved=True,whole_campaign_usage_complete=False,
        parent_result=dict(path=str(pair/'pair-result.json'),sha256=file_hash(pair/'pair-result.json')))
    save(pair/'next-admission-envelope.json',envelope)
    print(dict(repeat=repeat,grades=grades,known_tokens=snapshot['study']['tokens'],local_uncertainty=snapshot['study']['uncertain']),flush=True)
    phase_records={arm:read(pair/arm/'phase-journal.json') if (pair/arm/'phase-journal.json').exists() else {} for arm in ('B','C')}
    admission=repeat_admission(results,phase_records,snapshot)
    save(pair/'next-repetition-admission.json',admission)
    if not admission['admitted']:
        print(dict(cohort_stopped=True,admission=admission),flush=True)
        break
    if repeat<3:
        restore_start=time.monotonic()
        for arm in ('B','C'):
            restore(spec['sessions'][arm],FROZEN,pair/('preserved-final-'+arm),expected_current=results[arm]['source_manifest_after'])
        envelope=carry_execution_time(envelope,[time.monotonic()-restore_start])
        save(pair/'post-restore-admission-envelope.json',envelope)
save(RUN/'cohort-result.json',dict(registered_pairs=2,attempted_pairs=len(all_pairs),pairs=all_pairs,
    final_envelope=envelope,whole_campaign_usage_complete=False,
    semantic_attribution_proven=False,full_five_task_matrix_completed=False))
print(dict(cohort_finished=True,completed_pairs=len(all_pairs)),flush=True)
