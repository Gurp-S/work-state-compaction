"""Register and execute exactly one Bprime/C pair from closed residual budget."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.inventory import private_inventory
from acceptance_matrix_v1.paired_cell import Cell,save
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.workspace_runtime import provision_pair,environment_facts,qualify_pair
from native_evidence import state,import_evidence
from native_rollout_snapshot import capture_rollout
from wsc.source_reference_view import MODE
from native_incremental_candidate import POLICY
from run_matrix_first_slice import file_hash,workspace_manifest


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))


def prepare_pair(out,parent,executable,*,c_first=False,runtime=None):
    if runtime is None:raise ValueError('qualified_workspace_runtime_required')
    closure=read(parent/'closure.json');audit=inspect_ledger(parent/'coordinator-private/ledger.db')['state']
    parent_plan=read(parent/'registration.json')
    is_pair=parent_plan.get('status','').startswith('registered_pair_r')
    repeat=parent_plan.get('repeat',1)+1 if is_pair else 1
    if repeat>3:raise ValueError('registered_repeat_limit_reached')
    history_root=Path(parent_plan.get('history_control_root',str(Path(parent_plan['parent']).parent))) if is_pair else parent
    history_control=read(history_root/'closure.json')
    reconciliation=None
    if audit['budget']['study']['uncertain']:
        reconciliation=parent/'no-dispatch-reconciliation.json'
        derived=read(reconciliation)
        if derived.get('status')!='verified_no_model_dispatch' or derived.get('known_tokens')!=0 or derived.get('known_responses')!=0 \
                or derived['ledger_sha256']!=file_hash(parent/'coordinator-private/ledger.db') \
                or derived['closure_sha256']!=file_hash(parent/'closure.json'):
            raise ValueError('incomplete_parent_usage_not_reconciled')
    if not history_control.get('history_dependency_qualified') or audit['status']!='closed':
        raise ValueError('history_control_or_budget_not_qualified')
    if audit['budget']['study']!=closure['budget']['budget']['study']:
        raise ValueError('parent_usage_mismatch')
    readiness=read(ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json')
    matrix=read(ROOT/'reviews/acceptance-matrix-admission-20261028/registration.draft.json')
    fixture=Path(matrix['tasks']['T1']['fixture_root']);public=read(fixture/'history.public.json')
    if seal(public)!=matrix['tasks']['T1']['public_sha256']:raise ValueError('task_fixture_changed')
    presentation=history_root/'coordinator-private/A-session/after-import.jsonl'
    observed=state(capture_rollout(presentation).rows);count=len(observed)-len(public['prefix'])
    proof=import_evidence(observed[count:],public['prefix'])
    if count<0 or not proof['matched'] or proof['start_ordinal']!=0:raise ValueError('source_presentation_unbound')
    limits=closure['remaining_first_batch_limits']
    for k,spent in [('max_total_tokens','tokens'),('max_responses','responses')]:
        if limits[k]+audit['budget']['study'][spent]!=audit['budget']['study']['limits'][k]:
            raise ValueError('parent_remaining_changed')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    for name in ('Bprime','C'):
        shutil.copytree(fixture/'public-starter',out/name)
        (out/name/'canary.txt').write_text('owned-public-canary',encoding='utf-8')
    (out/'C-selector').mkdir()
    runtime_binding=provision_pair(runtime,out)
    blocked,_=private_inventory(ROOT,readiness)
    run_limit=dict(max_total_tokens=min(3000000,limits['max_total_tokens']//2),
                   max_responses=min(120,limits['max_responses']//2),max_seconds=min(1800,limits['max_seconds']))
    inputs=dict(prefix=public['prefix'],request=public['request']+'\n'+json.dumps(environment_facts(runtime_binding),sort_keys=True,separators=(',',':')))
    save(private/'inputs.json',inputs)
    sources=set((ROOT/'src/wsc').rglob('*.py'))|set((ROOT/'benchmarks/acceptance_matrix_v1').glob('*.py'))
    sources.update([Path(__file__).resolve(),ROOT/'benchmarks/deterministic_v1/native_blackbox_sessions.py',ROOT/'benchmarks/deterministic_v1/blackbox.py'])
    sources.update((ROOT/'experiments').glob('native_*.py'))
    plan=dict(status='registered_pair_r'+str(repeat),repeat=repeat,c_first=c_first,history_control_root=str(history_root),comparison='system_blackbox',model=matrix['models']['strong'],
        executable=str(executable.resolve()),executable_sha256=file_hash(executable),
        parent=str(parent/'closure.json'),parent_sha256=file_hash(parent/'closure.json'),
        parent_claim=str(parent/('paired-r'+str(repeat)+'-allocation.claim.json')),limits=limits,run_limits={name:run_limit for name in ('Bprime','C')},
        history_sha256=seal(public['prefix']),task_public_sha256=seal(public),runtime=runtime_binding,
        source_presentation=dict(path=str(presentation),sha256=file_hash(presentation),bootstrap_items=count,
                                 thread_id=read(history_root/'coordinator-private/A-session/opened.json')['thread']['id']),
        blocked=[str(p) for p in blocked]+[str(private),str(parent),str(history_root),str(Path(parent_plan['parent']).parent)],
        recovery_limits=dict(max_calls=8,max_rows_per_call=256,max_rows_total=512,max_chars=8192,
             max_matches=8,max_return_bytes=16384,max_row_bytes=1048576,max_text_bytes_total=2097152),
        input_sha256=file_hash(private/'inputs.json'),source_sha256={str(p):file_hash(p) for p in sorted(sources)},
        workspace_manifests={name:workspace_manifest(out/name) for name in ('Bprime','C')},
        selector_runtime='source_selector_minimal_v1',selector_model=matrix['models']['strong'],
        source_projection=MODE,policy=POLICY,
        compression_attempts=1,no_automatic_retries=True,capacity_status='unobserved',
        scope='One common-checkpoint pair; C normal model selection and source recovery; Bprime native compression without recovery.')
    if reconciliation:
        plan['source_sha256'][str(reconciliation)]=file_hash(reconciliation)
    save(out/'registration.json',plan)
    return plan


def execute_pair(out):
    plan=read(out/'registration.json')
    expected={**plan['source_sha256'],plan['parent']:plan['parent_sha256'],plan['executable']:plan['executable_sha256'],
              str(out/'coordinator-private/inputs.json'):plan['input_sha256'],plan['source_presentation']['path']:plan['source_presentation']['sha256']}
    for p,digest in expected.items():
        if file_hash(p)!=digest:raise ValueError('registered_input_changed:'+p)
    for name in ('Bprime','C'):
        if workspace_manifest(out/name)!=plan['workspace_manifests'][name]:raise ValueError('initial_workspace_changed')
    qualify_pair(plan,out)
    save(plan['parent_claim'],dict(child=str(out),limits=plan['limits'],parent_sha256=plan['parent_sha256'],allocation_not_actual_spend=True))
    runs={name:dict(arm=name,limits=plan['run_limits'][name],binding=dict(model=plan['model'],history_sha256=plan['history_sha256'],
        task='T1',repeat=plan.get('repeat',1),workspace=str(out/name))) for name in ('Bprime','C')}
    ledger=DispatchBudget(out/'coordinator-private/ledger.db',runs,plan['limits'])
    results={}
    try:
        inputs=read(out/'coordinator-private/inputs.json')
        if plan.get('c_first'):
            results['C']=Cell('C',plan,out,ledger,inputs).run()
            if results['C'].get('success'):
                results['Bprime']=Cell('Bprime',plan,out,ledger,inputs).run()
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs={name:pool.submit(Cell(name,plan,out,ledger,inputs).run) for name in runs}
                for name,job in jobs.items():results[name]=job.result()
    finally:
        snapshot=ledger.snapshot()
        save(out/'closure.json',dict(results=results,budget=snapshot,
            remaining_first_batch_limits=dict(max_total_tokens=max(0,plan['limits']['max_total_tokens']-snapshot['budget']['study']['tokens']),
             max_responses=max(0,plan['limits']['max_responses']-snapshot['budget']['study']['responses']),
             max_seconds=max(0,int(plan['limits']['max_seconds']-snapshot['active_seconds']))),
            old_unknowns_preserved=True,whole_campaign_usage_complete=False))
        ledger.close()
    print(json.dumps({name:value.get('success') for name,value in results.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--parent',type=Path);parser.add_argument('--executable',type=Path);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--c-first',action='store_true')
    parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.execute:execute_pair(args.out.resolve())
    else:print(json.dumps(prepare_pair(args.out.resolve(),args.parent.resolve(),args.executable,c_first=args.c_first,runtime=args.runtime),ensure_ascii=False)[:150])
