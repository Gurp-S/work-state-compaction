"""Only new hot continuations; reuse three historical choices and old controls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from wsc import WSC,Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import Limits,encode
from wsc.resource_io import ResourceIO
from wsc.source_access import SnapshotSourceAccess,SourceAccessLimits
from wsc.source_reference_view import MODE
from native_recorded_choice import reuse
from native_incremental_candidate import POLICY as SELECTION_POLICY
from native_hot_checkpoint import HotCheckpointAdapter,POLICY,engine_items,load_projection,validate_hot_recovery_aliases
from native_indexed_checkpoint import expand_working_state
from native_task_recovery import open_task_receiver
from native_blackbox_sessions import import_fresh
from acceptance_matrix_v1.paired_cell import Cell,NativeCheckpointHost,save,accept_t1,load_candidate
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.workspace_runtime import provision_pair
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.campaign_allocation import remaining
from run_matrix_first_slice import file_hash,workspace_manifest

BASE=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')
PARENT=Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1')
CASES={'r1':BASE,'r2':PARENT/'r2','r3':PARENT/'r3'}


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def core_for(folder,work,session):
    return WSC(Store(folder/'state.db',session_id=session,workspace=str(work)),access=lambda *a:True,
        resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')


def facts(items,reference):
    """Validate the complete state, compare the exact actor payload.

    New publications own different cold object paths in metadata; these are
    independently sealed by core.stage. The visible indexed header differs
    only in archive locators, while its aliases and literal tail must match.
    """
    metadata=load_projection(reference)
    index=[i for i,item in enumerate(items) if any(b.get('text','').startswith('{"archive":') for b in item.get('content',[]))]
    if len(index)!=1:raise ValueError('recorded_state_not_unique')
    i=index[0];text=items[i]['content'][0]['text']
    expand_working_state(text,metadata)
    first,tail=text.split('\n',1);header=json.loads(first);header.pop('archive')
    return header,tail,items[:i],items[i+1:]


def prepare(out,runtime):
    start=perf_counter();base=read(BASE/'registration.json');closed=inspect_ledger(PARENT/'coordinator-private/ledger.db')['state']
    if closed['status']!='closed' or closed['budget']['study']['uncertain']:raise ValueError('parent_not_closed_complete')
    if not all(read(PARENT/'closure.json')['valid_pairs'].values()):raise ValueError('parent_pairs_not_complete')
    if file_hash(base['executable'])!=base['executable_sha256']:raise ValueError('cli_changed')
    spent=closed['budget']['study'];allowance=dict(max_total_tokens=spent['limits']['max_total_tokens']-spent['tokens'],
        max_responses=spent['limits']['max_responses']-spent['responses'],max_seconds=int(spent['limits']['max_seconds']-closed['active_seconds']))
    limits=dict(max_total_tokens=900000,max_responses=24,max_seconds=900);remaining(allowance,[limits])
    claim=PARENT/'hot-continuation-probe.claim.json'
    if claim.exists():raise ValueError('probe_already_claimed')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    inputs=read(BASE/'coordinator-private/inputs.json');save(private/'inputs.json',inputs)
    fixture=Path(base['oracle_path']).parent.parent
    proof={};artifacts=set();runtime_binding=None
    for name,source in CASES.items():
        root=out/name;root.mkdir();(root/'coordinator-private/C').mkdir(parents=True)
        for peer in ('C-selector','Bprime'):(root/peer).mkdir()
        shutil.copytree(fixture/'public-starter',root/'C')
        runtime_binding=provision_pair(runtime,root,arms=('C',))
        if runtime_binding!=base['runtime']:raise ValueError('runtime_changed')
        work=root/'C';folder=root/'coordinator-private/C'
        core=core_for(folder,work,name);presentation=base['source_presentation']
        batch=CodexCheckpointAdapter().import_items(inputs['prefix'],thread_id=presentation['thread_id'],start_ordinal=presentation['bootstrap_items'])
        core.ingest(batch);core.presented('qualified-import:'+presentation['sha256'],tuple(e.id for e in batch if e.kind=='result'),receiver=presentation['thread_id'])
        snapshot=core.capture();selection,reuse_proof=reuse(core,snapshot,source)
        view=core.prepare(snapshot,selection,producer=SELECTION_POLICY['id'],source_projection=MODE,
            limits=Limits(max_material_bytes=SELECTION_POLICY['max_material_bytes'],max_view_bytes=SELECTION_POLICY['max_view_body_bytes']))
        operation=core.stage(view,directory=folder/'exports',archive_directory=folder/'cold-objects',adapter=HotCheckpointAdapter())
        package=core.package(operation)
        old=read(source/'coordinator-private/C/publication.json')['package']
        if encode(facts(engine_items(package),package['adapter']['projection_evidence']))!=encode(facts(old['items'],old['adapter']['projection_evidence'])):
            raise ValueError('same_choice_semantic_state_changed')
        proof[name]=dict(operation=operation,package_digest=package['package_digest'],reuse=reuse_proof,
            semantic_state_equal_except_engine_archive=True,old_continuation= str(source/'coordinator-private/C/continuation/phase-outcome.json'))
        for path in folder.rglob('*'):
            if path.is_file():artifacts.add(path)
        artifacts.update(source.rglob('compiled-draft.json'))
        artifacts.update([source/'coordinator-private/C/publication.json',source/'coordinator-private/C/selection/phase-outcome.json',
            source/'C-selector/generation/model-draft.json',source/'C-selector/generation/resource-manifest.json',
            source/'C-selector/generation/wire-bindings.json',source/'C-selector/generation/span-handle-bindings.json',
            Path(old['adapter']['projection_evidence']['file_path']),Path(old['understanding_index'])])
    blocked=set(Path(p) for p in base['blocked'])|{private,PARENT,BASE}
    for name in CASES:blocked.add(out/name/'coordinator-private')
    for pattern in ('wsc-matrix-*','wsc-hot-*','wsc-runtime-denoise-*'):
        blocked.update(p for p in out.parent.glob(pattern) if p.is_dir() and p!=out)
    sources=set((ROOT/'src/wsc').rglob('*.py'))|set((ROOT/'experiments').glob('native_*.py'))
    sources.update((ROOT/'benchmarks/acceptance_matrix_v1').glob('*.py'))
    sources.update((ROOT/'benchmarks/deterministic_v1').glob('*.py'))
    sources.update([Path(__file__).resolve(),ROOT/'validation/run_matrix_first_slice.py',
        ROOT/'reviews/2026-10-29-hot-continuation-probe-v1.md',PARENT/'closure.json',PARENT/'registration.json',
        PARENT/'coordinator-private/ledger.db',BASE/'registration.json',Path(base['oracle_path'])])
    plan=dict(status='registered_hot_only_same_draft_diagnostic',model=base['model'],executable=base['executable'],executable_sha256=base['executable_sha256'],
        parent=str(PARENT),claim=str(claim),parent_allowance=allowance,limits=limits,
        run_limits={'C':dict(max_total_tokens=300000,max_responses=8,max_seconds=450)},max_parallel=2,
        actor_projection_policy=POLICY,history_sha256=base['history_sha256'],recovery_limits=base['recovery_limits'],oracle_path=base['oracle_path'],
        proof=proof,workspace_names=['Bprime','C','C-selector'],blocked=[str(p) for p in sorted(blocked)],runtime=runtime_binding,
        source_sha256={str(p):file_hash(p) for p in sorted(sources|artifacts)},input_sha256=file_hash(private/'inputs.json'),
        workspace_manifests={name:workspace_manifest(out/name/'C') for name in CASES},
        preparation_seconds=perf_counter()-start,selector_calls=0,old_controls_rerun=False,
        original_selection_costs_retained=True,default_adapter_changed=False,
        scope='New hot continuation only, paired to immutable historical same-draft C controls. Different wall/cache/budget conditions; not a full-chain/native B superiority experiment.')
    save(out/'registration.json',plan)
    frozen={}
    for index,(name,expected) in enumerate(plan['source_sha256'].items()):
        original=Path(name)
        try:relative=Path('repo')/original.relative_to(ROOT)
        except ValueError:relative=Path('external')/(str(index)+'-'+original.name)
        target=private/'frozen-inputs'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        if file_hash(target)!=expected:raise ValueError('frozen_input_copy_changed')
        frozen[name]=dict(copy=str(target),sha256=expected)
    save(private/'frozen-inputs-manifest.json',frozen)
    return plan


class ProbeCell(Cell):
    def setup_receiver(self,label):
        self.core=core_for(self.folder,self.work,self.out.name)
        self.reader=SnapshotSourceAccess(self.core.store,self.core.capture(),access=self.core.access,limits=SourceAccessLimits(**self.plan['recovery_limits']))
        holder={}
        def factory(**kwargs):
            session,bootstrap=self.open(label,**kwargs);holder['bootstrap']=bootstrap;return session
        port=open_task_receiver(factory,self.reader)
        return port,holder['bootstrap']
    def run(self):
        ticket,phase=None,None;result=None
        try:
            ticket=self.start('continuation');port,bootstrap=self.setup_receiver('receiver')
            operation=self.plan['proof'][self.out.name]['operation']
            receipt=self.core.install(operation,NativeCheckpointHost(port,bootstrap,self.folder/'receiver-session'))
            save(self.folder/'publication.json',dict(receipt=receipt,package=self.core.package(operation)))
            phase=self.call(ticket,port.session,self.inputs['request'],'continuation',port=port)
            for session in self.sessions:self.close_session(session)
            self.settle(ticket,phase);ticket=None
            result=accept_t1(load_candidate(self.work/'retry_client.py'));result['task_success']=result['success']
            state=self.ledger.snapshot()['budget']
            result['run_success']=result['success']=bool(result['success'] and phase['completed'] and not phase['failure']
                and phase['usage_complete'] and not state['study']['uncertain'] and not state['arms'][self.run_id]['stopped'])
            save(self.folder/'recovery.json',dict(calls=self.reader.calls,trace=port.handler.trace,refused_callbacks=port.handler.refused_callbacks))
        except BaseException as error:
            if ticket is not None:self.settle(ticket,phase,error)
            result=dict(success=False,run_success=False,task_success=None,error=str(error))
        finally:
            cleanup=[self.close_session(session) for session in self.sessions]
            if result is not None:self.ledger.finish(self.run_id,result);save(self.folder/'result.json',dict(**result,cleanup=cleanup))
        return result


def execute(out):
    plan=read(out/'registration.json');private=out/'coordinator-private'
    for p,expected in {**plan['source_sha256'],plan['executable']:plan['executable_sha256'],str(private/'inputs.json'):plan['input_sha256']}.items():
        if file_hash(p)!=expected:raise ValueError('registered_input_changed:'+p)
    if Path(plan['claim']).exists():raise ValueError('probe_already_claimed')
    inputs=read(private/'inputs.json');plans={}
    for name in CASES:
        if workspace_manifest(out/name/'C')!=plan['workspace_manifests'][name]:raise ValueError('initial_workspace_changed')
        local=dict(plan,blocked=plan['blocked']+[str(out/peer) for peer in CASES if peer!=name]);plans[name]=local
        cell=ProbeCell('C',local,out/name,None,inputs,ledger_id=name,prepared_folder=True)
        try:
            port,bootstrap=cell.setup_receiver('preflight');package=cell.core.package(plan['proof'][name]['operation'])
            if package['package_digest']!=plan['proof'][name]['package_digest']:raise ValueError('prepared_package_changed')
            validate_hot_recovery_aliases(package,cell.reader)
            import_fresh(port.session,package['items'],bootstrap,cell.folder/'preflight-session')
        finally:save(cell.folder/'preflight-cleanup.json',[cell.close_session(s) for s in cell.sessions])
    save(plan['claim'],dict(child=str(out),limits=plan['limits'],registration_sha256=file_hash(out/'registration.json'),old_unknowns_preserved=True))
    runs={name:dict(arm='C_hot_probe',limits=plan['run_limits']['C'],binding=dict(history_sha256=plan['history_sha256'],workspace=str(out/name/'C'),draft=plan['proof'][name]['reuse'])) for name in CASES}
    ledger=DispatchBudget(private/'ledger.db',runs,plan['limits'],arm_token_ceiling=1000000);results={}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs={name:pool.submit(ProbeCell('C',plans[name],out/name,ledger,inputs,ledger_id=name,prepared_folder=True).run) for name in CASES}
            for name,job in jobs.items():results[name]=job.result()
    finally:
        ledger.close();snapshot=inspect_ledger(private/'ledger.db')['state'];evidence={}
        for name in results:
            phase=out/name/'coordinator-private/C/continuation/phase-outcome.json'
            if phase.exists():evidence[name]=score_final(read(phase),read(plan['oracle_path']))
        save(out/'structured-evidence.json',evidence)
        save(out/'closure.json',dict(results=results,budget=snapshot,old_controls_rerun=False,selector_calls=0,
            old_unknowns_preserved=True,whole_campaign_usage_complete=False,scope=plan['scope']))
    print(json.dumps({name:row.get('run_success') for name,row in results.items()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--runtime',type=Path);parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:execute(args.out.resolve())
    else:print(json.dumps(prepare(args.out.resolve(),args.runtime),ensure_ascii=False)[:150])
