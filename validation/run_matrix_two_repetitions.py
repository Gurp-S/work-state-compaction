"""Two fixed-strategy repeats, shared budget, maximum two model workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from acceptance_matrix_v1.paired_cell import Cell,save
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.campaign_allocation import remaining
from acceptance_matrix_v1.inventory import private_inventory
from acceptance_matrix_v1.workspace_runtime import provision_pair,qualify_pair
from acceptance_matrix_v1.final_assertions import score_final
from run_matrix_first_slice import file_hash,workspace_manifest

BASE=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')
CAMPAIGN=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1')
CLAIM=CAMPAIGN/'matrix-third-batch-20261029.claim.json'
PAIRS=('r2','r3')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(out,runtime):
    base=read(BASE/'registration.json');closed=read(BASE/'closure.json')
    previous=inspect_ledger(BASE/'coordinator-private/ledger.db')['state']
    if previous['status']!='closed' or previous['budget']['study']['uncertain'] or not closed['valid_pair']:
        raise ValueError('first_valid_pair_not_closed_complete')
    if not closed['history_dependency_qualified']:raise ValueError('current_history_baseline_not_qualified')
    allowed_change=ROOT/'benchmarks/acceptance_matrix_v1/paired_cell.py'
    for name,digest in base['source_sha256'].items():
        if Path(name)!=allowed_change and file_hash(name)!=digest:raise ValueError('fixed_comparison_source_changed:'+name)
    if file_hash(base['executable'])!=base['executable_sha256']:raise ValueError('native_cli_changed')
    reference=CAMPAIGN/'next-admission-envelope.json'
    claims=sorted(CAMPAIGN.glob('matrix-*.claim.json'))
    if {p.name for p in claims}!={'matrix-first-batch-20261028.claim.json','matrix-second-batch-20261028.claim.json'}:
        raise ValueError('campaign_allocation_changed')
    for path in claims:
        if read(path)['parent_sha256']!=file_hash(reference):raise ValueError('campaign_claim_reference_changed')
    limits=dict(max_total_tokens=2000000,max_responses=56,max_seconds=1600)
    after=remaining(read(reference)['remaining_limits'],[read(p)['limits'] for p in claims]+[limits])
    fixture=Path(base['oracle_path']).parent.parent
    public=read(fixture/'history.public.json')
    inputs=read(BASE/'coordinator-private/inputs.json')
    if file_hash(BASE/'coordinator-private/inputs.json')!=base['input_sha256']:raise ValueError('first_pair_input_changed')
    if public['prefix']!=inputs['prefix']:raise ValueError('fixture_prefix_changed')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    save(private/'inputs.json',inputs)
    runtime_binding=None
    for pair in PAIRS:
        folder=out/pair;folder.mkdir();(folder/'coordinator-private').mkdir();(folder/'C-selector').mkdir()
        for name in ('Bprime','C'):shutil.copytree(fixture/'public-starter',folder/name)
        binding=provision_pair(runtime,folder)
        if binding!=base['runtime']:raise ValueError('qualified_runtime_changed')
        runtime_binding=binding
        for name in ('Bprime','C'):
            if workspace_manifest(folder/name)!=base['workspace_manifests'][name]:raise ValueError('fixed_initial_workspace_changed')
    ready=read(ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json')
    blocked,_=private_inventory(ROOT,ready);blocked=set(blocked)|{private,CAMPAIGN,BASE}
    for pair in PAIRS:blocked.add(out/pair/'coordinator-private')
    for pattern in ('wsc-matrix-*','wsc-origin-*','wsc-deferred-*','wsc-blackbox-*'):
        blocked.update(path for path in out.parent.glob(pattern) if path.is_dir() and path!=out)
    sources=set((ROOT/'src/wsc').rglob('*.py'))|set((ROOT/'experiments').glob('native_*.py'))
    sources.update((ROOT/'benchmarks/acceptance_matrix_v1').glob('*.py'))
    sources.update((ROOT/'benchmarks/deterministic_v1').glob('*.py'))
    sources.update([Path(__file__).resolve(),ROOT/'validation/run_matrix_first_slice.py',
        ROOT/'reviews/2026-10-29-acceptance-matrix-execution-v1.7.md',reference,*claims,
        BASE/'registration.json',BASE/'closure.json',BASE/'coordinator-private/ledger.db',
        Path(base['source_presentation']['path']),Path(base['oracle_path'])])
    plan=dict(status='registered_T1_repetitions_2_3',baseline=str(BASE),baseline_sha256=file_hash(BASE/'registration.json'),
        comparison='system_blackbox',pairs=list(PAIRS),max_parallel=2,schedule='parallel_C_then_parallel_Bprime',
        model=base['model'],executable=base['executable'],executable_sha256=base['executable_sha256'],
        limits=limits,run_limits={name:base['run_limits'][name] for name in ('Bprime','C')},
        arm_prior_allocations_withheld=4000000,arm_remaining_token_ceiling=11000000,
        root_reference=str(reference),root_reference_sha256=file_hash(reference),claim=str(CLAIM),
        prior_claim_hashes={str(p):file_hash(p) for p in claims},remaining_reference_allocation=after,
        second_batch_remainder_not_reclaimed=True,old_failures_and_unknowns_preserved=True,
        whole_campaign_usage_complete=False,runtime=runtime_binding,
        blocked=[str(p.resolve()) for p in sorted(blocked)],workspace_names=['Bprime','C','C-selector'],
        history_sha256=base['history_sha256'],source_presentation=base['source_presentation'],
        recovery_limits=base['recovery_limits'],oracle_path=base['oracle_path'],
        input_sha256=file_hash(private/'inputs.json'),
        workspace_manifests={pair:{name:workspace_manifest(out/pair/name) for name in ('Bprime','C')} for pair in PAIRS},
        source_sha256={str(p):file_hash(p) for p in sorted(sources)},
        canonical_Cell_behavior_unchanged=True,actor_change='Optional ledger identity namespace only; actor name, source strategy, model text unchanged.',
        no_automatic_retries=True,compression_attempts=1,
        timing_limitations='First pair was serial after baselines; repetitions use two workers. Timing comparisons are descriptive, not a causal algorithm speed estimate.')
    save(out/'registration.json',plan)
    for index,(name,digest) in enumerate(plan['source_sha256'].items()):
        path=Path(name)
        try:relative=path.relative_to(ROOT)
        except ValueError:relative=Path('external')/(str(index)+'-'+path.name)
        target=private/'frozen-source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        if file_hash(target)!=digest:raise ValueError('source_snapshot_changed')
    return plan


def execute(out):
    plan=read(out/'registration.json');private=out/'coordinator-private'
    for name,digest in {**plan['source_sha256'],plan['executable']:plan['executable_sha256'],str(private/'inputs.json'):plan['input_sha256']}.items():
        if file_hash(name)!=digest:raise ValueError('registered_input_changed:'+name)
    if {str(p) for p in CAMPAIGN.glob('matrix-*.claim.json')}!=set(plan['prior_claim_hashes']):
        raise ValueError('campaign_allocation_changed')
    if Path(plan['claim']).exists():raise ValueError('allocation_already_claimed')
    inputs=read(private/'inputs.json');pair_plans={}
    for pair in PAIRS:
        for name in ('Bprime','C'):
            if workspace_manifest(out/pair/name)!=plan['workspace_manifests'][pair][name]:raise ValueError('initial_workspace_changed')
        pair_plan=dict(plan,blocked=plan['blocked']+[str(out/peer) for peer in PAIRS if peer!=pair])
        qualify_pair(pair_plan,out/pair,material_inputs=inputs)
        pair_plans[pair]=pair_plan
    save(plan['claim'],dict(child=str(out),limits=plan['limits'],parent_sha256=plan['root_reference_sha256'],
        registration_sha256=file_hash(out/'registration.json'),allocation_is_not_spend=True,old_unknowns_preserved=True))
    runs={pair+':'+name:dict(arm=name,limits=plan['run_limits'][name],binding=dict(model=plan['model'],
        history_sha256=plan['history_sha256'],task='T1',repeat=pair,workspace=str(out/pair/name))) for pair in PAIRS for name in ('C','Bprime')}
    ledger=DispatchBudget(private/'ledger.db',runs,plan['limits'],arm_token_ceiling=plan['arm_remaining_token_ceiling'])
    results={pair:{} for pair in PAIRS}
    try:
        for name in ('C','Bprime'):
            if name=='Bprime' and not all(results[pair].get('C',{}).get('run_success') for pair in PAIRS):break
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs={pair:pool.submit(Cell(name,pair_plans[pair],out/pair,ledger,inputs,ledger_id=pair+':'+name).run) for pair in PAIRS}
                for pair,job in jobs.items():results[pair][name]=job.result()
    finally:
        ledger.close();snapshot=inspect_ledger(private/'ledger.db')['state']
        evidence={}
        for pair in PAIRS:
            evidence[pair]={}
            for name in results[pair]:
                phase=out/pair/'coordinator-private'/name/'continuation/phase-outcome.json'
                if phase.exists():evidence[pair][name]=score_final(read(phase),read(plan['oracle_path']))
        save(out/'structured-evidence.json',evidence)
        save(out/'closure.json',dict(results=results,budget=snapshot,old_failures_and_unknowns_preserved=True,
            whole_campaign_usage_complete=False,valid_pairs={pair:all(results[pair].get(name,{}).get('run_success') for name in ('C','Bprime')) for pair in PAIRS}))
    print(json.dumps({pair:{name:value.get('run_success') for name,value in row.items()} for pair,row in results.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--runtime',type=Path);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:execute(args.out.resolve())
    else:print(json.dumps(prepare(args.out.resolve(),args.runtime),ensure_ascii=False)[:180])
