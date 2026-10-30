"""One preregistered runtime-controlled admission group; no automatic retries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from acceptance_matrix_v1.campaign_allocation import remaining
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.baseline_cell import BaselineCell
from acceptance_matrix_v1.paired_cell import Cell,save
from acceptance_matrix_v1.inventory import private_inventory
from acceptance_matrix_v1.workspace_runtime import provision_pair,environment_facts,qualify_pair
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.followup_allocation import followup
from native_evidence import state,import_evidence
from native_rollout_snapshot import capture_rollout
from run_matrix_first_slice import file_hash,workspace_manifest

NAMES=('A','last-state-only','Bprime','C')
PARENT=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1')
FIRST=PARENT/'matrix-first-batch-20261028.claim.json'
SECOND=PARENT/'matrix-second-batch-20261028.claim.json'
PREVIOUS=Path('D:/agent-task-runs/wsc-matrix-first-pair-20261028-r2-v2')
HISTORY=Path('D:/agent-task-runs/wsc-matrix-first-controls-20261028-v1')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(out,executable,runtime,*,continuation=None):
    reference=PARENT/'next-admission-envelope.json'
    ready=read(ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json')
    if file_hash(reference)!=ready['previous_envelope_sha256']:raise ValueError('reference_changed')
    expected_claims={FIRST,SECOND} if continuation else {FIRST}
    if set(PARENT.glob('matrix-*.claim.json'))!=expected_claims:raise ValueError('unexpected_or_already_claimed_allocation')
    first=read(FIRST)
    if first['parent_sha256']!=file_hash(reference):raise ValueError('first_claim_reference_changed')
    previous=inspect_ledger(PREVIOUS/'coordinator-private/ledger.db')['state']
    if previous['status']!='closed' or not previous['budget']['study']['uncertain']:
        raise ValueError('expected_closed_unknown_predecessor_changed')
    context=followup(continuation) if continuation else None
    if context and Path(read(SECOND)['child']).resolve()!=Path(continuation).resolve():
        raise ValueError('continuation_not_second_allocation_owner')
    limits=context['limits'] if context else dict(max_total_tokens=2000000,max_responses=64,max_seconds=2400)
    allocation_after=remaining(read(reference)['remaining_limits'],[first['limits'],read(SECOND)['limits'] if context else limits])
    root_reference=reference
    if context:reference=context['reference']
    matrix=read(ROOT/'reviews/acceptance-matrix-admission-20261028/registration.draft.json')
    fixture=Path(matrix['tasks']['T1']['fixture_root']);public=read(fixture/'history.public.json')
    if seal(public)!=matrix['tasks']['T1']['public_sha256']:raise ValueError('fixture_changed')
    presentation=HISTORY/'coordinator-private/A-session/after-import.jsonl'
    observed=state(capture_rollout(presentation).rows);count=len(observed)-len(public['prefix'])
    if count<0 or not import_evidence(observed[count:],public['prefix'])['matched']:
        raise ValueError('original_source_presentation_changed')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    for name in NAMES:shutil.copytree(fixture/'public-starter',out/name)
    (out/'C-selector').mkdir()
    binding=provision_pair(runtime,out,arms=NAMES)
    request=public['request']+'\n'+json.dumps(environment_facts(binding),sort_keys=True,separators=(',',':'))
    save(private/'inputs.json',dict(prefix=public['prefix'],request=request))
    blocked,_=private_inventory(ROOT,ready)
    blocked=set(blocked)|{private,PARENT,HISTORY,PREVIOUS,Path(first['child'])}
    # Prior run logs and candidate artifacts contain contract answers, too.
    for pattern in ('wsc-matrix-*','wsc-origin-*','wsc-deferred-*','wsc-blackbox-*'):
        blocked.update(p for p in out.parent.glob(pattern) if p.is_dir() and p!=out)
    amendment=ROOT/'reviews/2026-10-29-acceptance-matrix-execution-v1.6.md' if context else ROOT/'reviews/2026-10-28-acceptance-matrix-execution-v1.5.md'
    sources=set((ROOT/'src/wsc').rglob('*.py'))|set((ROOT/'experiments').glob('native_*.py'))
    sources.update((ROOT/'benchmarks/acceptance_matrix_v1').glob('*.py'))
    sources.update((ROOT/'benchmarks/deterministic_v1').glob('*.py'))
    sources.update([Path(__file__).resolve(),ROOT/'validation/run_matrix_first_slice.py',amendment,
        ROOT/'reviews/2026-10-28-acceptance-matrix.md',reference,FIRST,
        PREVIOUS/'closure.json',PREVIOUS/'coordinator-private/ledger.db',presentation,
        ROOT/'reviews/acceptance-matrix-admission-20261028/first-pair-results.json',
        fixture/'coordinator-private/oracle.json'])
    sources.update(expected_claims)
    if context:sources.update([root_reference,*context['extra_sources']])
    plan=dict(status='registered_runtime_controlled_admission_v1',comparison='system_blackbox',
        original_pair_attempt_sequence=4 if context else 3,fixed_version_valid_pairs_before=0,
        executable=str(executable.resolve()),executable_sha256=file_hash(executable),model=matrix['models']['strong'],
        limits=limits,run_limits=context['run_limits'] if context else {name:dict(max_total_tokens=500000,max_responses=16,max_seconds=900) for name in NAMES},
        parent=str(reference),parent_sha256=file_hash(reference),parent_claim=str(context['parent_claim'] if context else SECOND),
        allocation_claim_hashes={str(p):file_hash(p) for p in sorted(expected_claims)},
        allocation_after=allocation_after,first_allocation_withheld=first['limits'],
        historical_uncertainty=True,whole_campaign_usage_complete=False,
        allocation_scope='Full first allocation withheld, not a proven upper bound on unknown provider charges.',
        arm_prior_allocation_withheld=2000000,arm_remaining_token_ceiling=13000000,
        source_sha256={str(p):file_hash(p) for p in sorted(sources)},
        history_sha256=seal(public['prefix']),task_public_sha256=seal(public),
        input_sha256=file_hash(private/'inputs.json'),oracle_path=str(fixture/'coordinator-private/oracle.json'),runtime=binding,runtime_arms=list(NAMES),
        workspace_names=list(NAMES)+['C-selector'],workspace_manifests={name:workspace_manifest(out/name) for name in NAMES},
        blocked=[str(p.resolve()) for p in sorted(blocked)],
        source_presentation=dict(path=str(presentation),sha256=file_hash(presentation),bootstrap_items=count,
            thread_id=read(HISTORY/'coordinator-private/A-session/opened.json')['thread']['id']),
        recovery_limits=dict(max_calls=8,max_rows_per_call=256,max_rows_total=512,max_chars=8192,
            max_matches=8,max_return_bytes=16384,max_row_bytes=1048576,max_text_bytes_total=2097152),
        compression_attempts=1,no_automatic_retries=True,capacity_status='unobserved',
        gates=['current_A_complete_and_passed','current_no_history_complete_and_failed','C_complete_and_passed_before_Bprime'],
        scope='One T1 strong-model admission group, not three valid fixed-version repetitions or full matrix qualification.')
    if context:
        plan.update(status='registered_runtime_controlled_followup_v1',
            continuation_parent=str(continuation),whole_second_allocation_still_withheld=True)
    save(out/'registration.json',plan)
    frozen=private/'frozen-source'
    for index,(name,digest) in enumerate(plan['source_sha256'].items()):
        source=Path(name)
        try:relative=source.relative_to(ROOT)
        except ValueError:relative=Path('external')/(str(index)+'-'+source.name)
        target=frozen/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if file_hash(target)!=digest:raise ValueError('source_snapshot_changed')
    return plan


def execute(out):
    plan=read(out/'registration.json')
    sealed={**plan['source_sha256'],plan['executable']:plan['executable_sha256'],
        str(out/'coordinator-private/inputs.json'):plan['input_sha256']}
    for path,digest in sealed.items():
        if file_hash(path)!=digest:raise ValueError('frozen_input_changed:'+path)
    claims=plan.get('allocation_claim_hashes',{str(FIRST):file_hash(FIRST)})
    if {str(p) for p in PARENT.glob('matrix-*.claim.json')}!=set(claims) or any(file_hash(p)!=d for p,d in claims.items()):
        raise ValueError('allocation_already_claimed_or_changed')
    if Path(plan['parent_claim']).exists():raise ValueError('followup_already_claimed')
    for name in NAMES:
        if workspace_manifest(out/name)!=plan['workspace_manifests'][name]:raise ValueError('initial_workspace_changed')
    qualify_pair(plan,out,material_inputs=read(out/'coordinator-private/inputs.json'))
    save(plan['parent_claim'],dict(child=str(out),limits=plan['limits'],parent_sha256=plan['parent_sha256'],
        registration_sha256=file_hash(out/'registration.json'),allocation_is_not_spend=True,
        old_unknowns_preserved=True,first_allocation_withheld=plan['first_allocation_withheld']))
    runs={name:dict(arm=name,limits=plan['run_limits'][name],binding=dict(model=plan['model'],
        history_sha256=seal([]) if name=='last-state-only' else plan['history_sha256'],task='T1',workspace=str(out/name))) for name in NAMES}
    ledger=DispatchBudget(out/'coordinator-private/ledger.db',runs,plan['limits'],arm_token_ceiling=plan['arm_remaining_token_ceiling'])
    inputs=read(out/'coordinator-private/inputs.json');results={};qualified=False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs={name:pool.submit(BaselineCell(name,plan,out,ledger,inputs).run) for name in ('A','last-state-only')}
            for name,job in jobs.items():results[name]=job.result()
        qualified=bool(results['A'].get('run_success') and results['last-state-only'].get('execution_complete')
            and results['last-state-only'].get('task_success') is False)
        save(out/'baseline-gate.json',dict(qualified=qualified,results=results))
        if qualified:
            results['C']=Cell('C',plan,out,ledger,inputs).run()
            if results['C'].get('run_success'):results['Bprime']=Cell('Bprime',plan,out,ledger,inputs).run()
    finally:
        ledger.close()
        snapshot=inspect_ledger(out/'coordinator-private/ledger.db')['state']
        evidence={}
        for name in results:
            phase=out/'coordinator-private'/name/'continuation/phase-outcome.json'
            if phase.exists():evidence[name]=score_final(read(phase),read(plan['oracle_path']))
        save(out/'structured-evidence.json',evidence)
        save(out/'closure.json',dict(results=results,budget=snapshot,history_dependency_qualified=qualified,
            old_unknowns_preserved=True,whole_campaign_usage_complete=False,
            valid_pair=bool(results.get('C',{}).get('run_success') and results.get('Bprime',{}).get('run_success')),
            source_version=plan['status'],remaining_allocation_dispatchable=False))
    print(json.dumps({name:dict(task_success=value.get('task_success'),run_success=value.get('run_success')) for name,value in results.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--executable',type=Path);parser.add_argument('--runtime',type=Path);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--continue-from',type=Path)
    args=parser.parse_args()
    if args.execute:execute(args.out.resolve())
    else:print(json.dumps(prepare(args.out.resolve(),args.executable,args.runtime,continuation=args.continue_from),ensure_ascii=False)[:200])
