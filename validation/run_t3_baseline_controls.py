"""One preregistered T3 history-dependence pair; no retries or old T1 runs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.campaign_allocation import remaining
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.task_cell import TaskBaselineCell
from acceptance_matrix_v1.workspace_runtime import verify_runtime,digest
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.paired_cell import save
from acceptance_matrix_v1.final_origin import score_bound_final

PARENT=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1')
PARENT_SHA='cbf8bc5592dd873ab2394ea2b9f2e2f322c77b4d55c9c1498cd6f0749dab41af'
CLAIM=PARENT/'matrix-t3-controls-20261029.claim.json'
ARM=dict(max_total_tokens=350000,max_responses=14,max_seconds=600)
LIMITS=dict(max_total_tokens=700000,max_responses=28,max_seconds=1200)


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def allocation():
    envelope=PARENT/'next-admission-envelope.json'
    if digest(envelope)!=PARENT_SHA:raise ValueError('t3_parent_envelope_changed')
    if CLAIM.exists():raise ValueError('t3_controls_already_claimed')
    paths=sorted(PARENT.glob('matrix-*.claim.json'))
    claims=[read(p)['limits'] for p in paths]
    residual=remaining(read(envelope)['remaining_limits'],claims)
    return dict(before=residual,after=remaining(residual,[LIMITS]),
                claims={str(p):digest(p) for p in paths})


def prepare(out):
    if read(out/'results.json').get('qualified') is not True:raise ValueError('t3_runtime_unqualified')
    plan=read(out/'registration.json')
    if plan['task_id']!='T3' or plan.get('runtime_startup_flags'):raise ValueError('t3_nondefault_actor_configuration')
    inputs=read(out/'coordinator-private/inputs.json')
    if seal(inputs)!=plan['inputs_sha256']:raise ValueError('t3_inputs_changed')
    if any((out/'coordinator-private'/name).exists() for name in ('A','last-state-only')):raise ValueError('t3_actor_already_prepared')
    for name in ('A','last-state-only'):
        verify_runtime(out/name/'.runtime')
        if digest(out/name/'.runtime/runtime-manifest.json')!=plan['runtime']['manifest_sha256']:raise ValueError('t3_runtime_manifest_changed')
    source_names=['benchmarks/acceptance_matrix_v1/task_cell.py','benchmarks/acceptance_matrix_v1/paired_cell.py',
        'benchmarks/acceptance_matrix_v1/baseline_cell.py','benchmarks/acceptance_matrix_v1/permissions.py',
        'benchmarks/acceptance_matrix_v1/acceptors.py','benchmarks/acceptance_matrix_v1/dispatch_budget.py',
        'benchmarks/acceptance_matrix_v1/acceptor_t3_v2.py','benchmarks/acceptance_matrix_v1/final_origin.py',
        'benchmarks/acceptance_matrix_v1/final_assertions.py','benchmarks/acceptance_matrix_v1/evidence.py',
        'benchmarks/deterministic_v1/native_blackbox_sessions.py','experiments/native_rpc.py',
        'experiments/native_owned_process.py','experiments/native_application_session.py',
        'validation/run_t3_baseline_controls.py']
    oracle=Path('D:/agent-task-runs/wsc-matrix-task-admission-20261028-v2/T3/coordinator-private/oracle.json')
    files=[ROOT/p for p in source_names]+[oracle,out/'registration.json',out/'results.json',out/'coordinator-private/inputs.json']
    for name in ('A','last-state-only'):
        files.extend(out/name/p for p in ('migrate.py','test_smoke.py'))
    registered=dict(schema='wsc.t3.history_controls/1',scope='System-level history admission only; no WSC/native compaction comparison',
        task_id='T3',model=plan['model'],run_limits={name:ARM for name in ('A','last-state-only')},limits=LIMITS,
        model_temperature=None,model_seed=None,max_parallel=2,no_automatic_retry=True,
        task_evaluator_policy='implementation_neutral_t3_v2',final_origin_policy='bound_model_response_item_v1',oracle_path=str(oracle),
        source_sha256={str(p):digest(p) for p in files},executable_sha256=plan['executable_sha256'],
        allocation=allocation(),parent_sha256=PARENT_SHA,claim=str(CLAIM),old_failures_and_unknowns_preserved=True,
        history_gate='Full-history run must complete and pass; last-state-only run must complete but fail task acceptance. Both pass => task not history-dependent.',
        incomplete_gate='Incomplete usage, model/provider/tool failure or uncertain ledger => no qualification conclusion; no automatic rerun.')
    save(out/'controls-registration.json',registered)
    return registered


def execute(out):
    reg=read(out/'controls-registration.json')
    for path,expected in reg['source_sha256'].items():
        if digest(path)!=expected:raise ValueError('t3_registered_source_changed:'+path)
    plan=read(out/'registration.json');inputs=read(out/'coordinator-private/inputs.json')
    if digest(plan['executable'])!=reg['executable_sha256']:raise ValueError('t3_cli_changed')
    if allocation()!=reg['allocation']:raise ValueError('t3_allocation_changed')
    private=out/'coordinator-private'
    ledger_path=private/'controls-ledger.db'
    if ledger_path.exists():raise ValueError('t3_existing_ledger_cannot_dispatch')
    save(CLAIM,dict(child=str(out),limits=LIMITS,parent_sha256=PARENT_SHA,
        registration_sha256=digest(out/'controls-registration.json'),allocation_is_not_spend=True,old_unknowns_preserved=True))
    runs={f'T3:{name}':dict(arm=name,limits=ARM,binding=dict(task_id='T3',workspace=str(out/name),
        history_sha256=seal(inputs['prefix'] if name=='A' else []),request_sha256=sha256(inputs['request'].encode()).hexdigest(),model=plan['model']))
        for name in ('A','last-state-only')}
    ledger=DispatchBudget(ledger_path,runs,LIMITS)
    plan=dict(plan,run_limits={name:ARM for name in ('A','last-state-only')},
        task_evaluator_policy=reg['task_evaluator_policy'])
    results={}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs={name:pool.submit(TaskBaselineCell(name,plan,out,ledger,inputs,task_id='T3',ledger_id='T3:'+name).run)
                  for name in ('A','last-state-only')}
            for name,job in jobs.items():
                try:results[name]=job.result()
                except BaseException as error:results[name]=dict(success=False,execution_complete=False,error=str(error))
    finally:
        ledger.close();state=inspect_ledger(ledger_path)['state']
        final_evidence={}
        for name in results:
            area=private/name/'continuation'
            try:
                final_evidence[name]=score_bound_final(read(area/'phase-outcome.json'),read(reg['oracle_path']),area/'rollout.jsonl')
            except (OSError,ValueError,KeyError,TypeError) as error:
                final_evidence[name]=dict(assessment_status='unassessable',reason=str(error))
        save(out/'controls-final-evidence.json',final_evidence)
        complete=all(r.get('execution_complete') is True for r in results.values()) and len(results)==2
        qualified=bool(complete and results['A'].get('task_success') is True and results['last-state-only'].get('task_success') is False)
        save(out/'controls-closure.json',dict(results=results,budget=state,history_dependency_qualified=qualified,
            task_evaluator_policy=reg['task_evaluator_policy'],final_origin_policy=reg['final_origin_policy'],
            execution_complete=complete,old_T1_rerun=False,old_unknowns_preserved=True,
            WSC_vs_native_comparison=False,no_automatic_retry=True))
    print(json.dumps(dict(history_dependency_qualified=qualified,execution_complete=complete)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if a.execute:execute(a.out.resolve())
    else:print(json.dumps(prepare(a.out.resolve())))
