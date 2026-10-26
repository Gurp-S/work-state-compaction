"""Same interrupted S2 prefix, independent continuation workspaces and billing."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,digest,manifest,FIELDS
from native_application_session import NativeApplicationSession
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope
from native_application_worker import ApplicationStudyWorker
from native_application_adapters import FrozenApplicationAdapters
from native_paired_admission import PairedAdmission
from native_application_capability import admit as admit_capability
from native_common_prefix import restore
from native_incremental_candidate import frontier
from native_incremental_generation import output_schema
import native_cold_access
from native_typed_content import TypedNativeAdapter,dependencies as media_dependencies
from native_span_handles import project as project_span_handles
sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store

AREA=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
PRIOR=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v3')


def sources(reg,destination):
    checker=NativeApplicationSession(reg,destination)
    return checker.source_manifest()


def prepare():
    stage=AREA/'staged'
    stage.mkdir(exist_ok=False)
    reg=read(PRIOR/'registration.json')
    outcome=read(PRIOR/'result.json')
    assert not outcome['ledger']['inflight']
    assert all(item['empty_confirmed'] for worker in outcome['outcomes'].values() for item in worker['cleanup'])
    binding=read(reg['tasks']['a3']['binding'])
    old_payload={arm:read(Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v3/prepared')/('payload-'+arm+'.json')) for arm in ('B','C')}
    breg=old_payload['B']['registration']
    before=sources(breg,stage/'source-audit-before')
    common=stage/'frozen-workspace'
    common.mkdir()
    for key,value in before.items():
        source=Path(breg['workspace'])/key
        target=common/key
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        assert file_hash(target)==value
    assert sources(breg,stage/'source-audit-after')==before
    assert manifest(common)==before
    if manifest(common/'gui/src')!=read(AREA/'S2-source-acceptance/registration.json')['source_manifest']:
        raise ValueError('shared_S2_source_changed_after_grade')
    assert all(file_hash(common/key)==value for key,value in binding['source_manifest'].items() if key.startswith('task-contract/'))
    output=PRIOR/'arms/B/output'
    started=read(output/'initial/thread-start.json')['thread']
    closed=output/'final-threads/000.jsonl'
    assert Path(started['path']).read_bytes()==closed.read_bytes()
    shutil.copyfile(closed,stage/'original-root.jsonl')
    first=read(output/'S1-phase/phase-outcome.json')
    parent_reg={**breg,'workspace':str(common),'initial_manifest':before,
        'parent_thread_id':started['id'],'parent_paths':{started['id']:started['path']}}
    for key in ('browser_cache','browser_probe','browser_probe_sha256'):
        parent_reg.pop(key,None)
    parent=NativeForkSession(parent_reg,stage/'common-parent')
    grade=read(AREA/'S2-grade.json')
    fact=dict(kind='independent_check_observation',stage='S2',source_manifest_sha256=grade['source_manifest_sha256'],
        checks=grade['observations'],observed_at=grade['observed_at'],artifact=grade['artifact'])
    try:
        parent.open()
        assert parent.fork_binding['parents'][0]['prefix_sha256']==file_hash(closed)
        parent.inject([dict(type='message',role='developer',content=[dict(type='input_text',text=json.dumps(fact,ensure_ascii=False,sort_keys=True,separators=(',',':')))])])
    finally:
        parent_cleanup=parent.close()
    parent_path=Path(parent.opened['thread']['path'])
    shutil.copyfile(parent_path,stage/'common-parent-closed.jsonl')
    capsule=dict(kind='shared_interrupted_S2_prefix_v1',source_workspace=breg['workspace'],source_manifest=before,
        native_S2_turn_completed=False,S2_automatic_passed=all(row['passed'] for row in grade['observations']),
        root_history=dict(thread_id=started['id'],native_path=started['path'],archive=str(stage/'original-root.jsonl'),
            sha256=file_hash(stage/'original-root.jsonl'),first_business_row=first['turn_accounting']['before']['records']),
        parent_thread_id=parent.opened['thread']['id'],parent_native_path=str(parent_path),parent_sha256=file_hash(parent_path),
        grade_fact=fact,shared_prefix_cost=outcome['outcomes']['B']['phases'],
        shared_prefix_cost_complete=False,shared_prefix_cost_scope='Known sunk prefix receipts, charged once in history; not new arm spend',
        parent_cleanup=parent_cleanup)
    capsule_path=stage/'capsule.json'
    save(capsule_path,capsule)
    prefix=dict(capsule=str(capsule_path),capsule_sha256=file_hash(capsule_path),
        reset_parent_thread_id=started['id'],reset_before_turn_id=first['turn_accounting']['turn_id'])
    parent_paths={started['id']:started['path'],parent.opened['thread']['id']:str(parent_path)}
    jobs=[]
    payloads={}
    for index,arm in enumerate(('B','C')):
        work=AREA/'arms'/arm/'workspace'
        shutil.copytree(common,work)
        oldwork=Path(old_payload[arm]['registration']['workspace']).resolve()
        for relative in ('gui/node_modules','.wsc-runtime'):
            source=(oldwork/relative).resolve()
            target=(work/relative).resolve()
            assert source.is_relative_to(oldwork) and target.is_relative_to(work.resolve())
            assert source.is_dir() and not target.exists()
            target.parent.mkdir(parents=True,exist_ok=True)
            save(stage/(arm+'-'+relative.replace('/','_')+'-move.json'),dict(source=str(source),destination=str(target),
                previous_closed_worker=str(PRIOR/'arms'/arm/'output/worker-result.json')))
            source.replace(target)
        current={**old_payload[arm]['registration'],'workspace':str(work),'initial_manifest':before,
            'browser_cache':str(work/'.wsc-runtime/browsers'),'browser_probe':str(work/'.wsc-runtime/browser-capability.mjs'),
            'parent_thread_id':parent.opened['thread']['id'],'parent_paths':parent_paths}
        assert sources(current,stage/('branch-source-'+arm))==before
        payload={**old_payload[arm],'registration':current,'common_prefix':prefix}
        path=stage/('payload-'+arm+'.json')
        save(path,payload)
        payloads[str(path)]=file_hash(path)
        jobs.append(dict(pair_id='a3/sharedS2',arm=arm,resources=dict(workspace=str(work),output=str(AREA/'arms'/arm/'output'),
            browser_profile=str(AREA/'arms'/arm/'browser-profile'),ports=[29400+3*index+i for i in range(3)])))
    conditions=deepcopy(reg['conditions'])
    conditions['verify_native_cold_access']=True
    conditions['comparison_scope']='Continuation after identical sealed interrupted S2 state; shared prefix charged once, not from-zero task cost'
    for job in jobs:
        job['conditions_sha256']=digest(conditions)
    save(stage/'prepared.json',dict(conditions=conditions,jobs=jobs,payload_files=payloads,tasks=reg['tasks'],
        expected_checks=reg['expected_checks'],node_executable=reg['node_executable'],capsule=str(capsule_path),
        capsule_sha256=file_hash(capsule_path),prefix_phases_reexecuted=0,new_model_calls=0))
    print('same S2 source/history staged; no prefix model rerun',flush=True)


def preflight():
    prepared=read(AREA/'staged/prepared.json')
    capsule=read(prepared['capsule'])
    observations={}
    tag=sys.argv[2] if len(sys.argv)>2 else 'preflight'
    for arm in ('B','C'):
        payload=read(AREA/'staged'/('payload-'+arm+'.json'))
        session=NativeForkSession(payload['registration'],AREA/(tag+'-'+arm))
        try:
            session.open()
            admit_capability(session,AREA/(tag+'-'+arm+'-browser'))
            first=session.fork_binding['parents'][0]
            assert first['prefix_sha256']==capsule['parent_sha256']
            observations[arm]=dict(parent_sha256=first['prefix_sha256'])
            if arm=='C':
                core=WSC(Store(AREA/(tag+'-wsc.db'),session_id='a3/sharedS2-'+tag,workspace=payload['registration']['workspace']),access=lambda *args:True)
                adapter=TypedNativeAdapter(AREA/(tag+'-media')) if prepared['conditions'].get('typed_native_content') else None
                restore(core,payload['common_prefix'],session,AREA/(tag+'-source-load.json'),adapter)
                material,offered=frontier(core,core.capture(),None,AREA/(tag+'-cold'))
                wire,bindings=project_span_handles(offered) if prepared['conditions'].get('short_span_handles') else (offered,None)
                schema=output_schema(wire)
                save(AREA/(tag+'-selection-schema.json'),schema)
                native_cold_access.material(session,offered,AREA/(tag+'-native-cold-access'),media_dependencies(core))
                observations[arm].update(material_bytes=len(json.dumps(offered,ensure_ascii=False,separators=(',',':')).encode()),
                    wire_material_bytes=len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()),
                    schema_bytes=len(json.dumps(schema,separators=(',',':')).encode()),
                    events=len(offered['events']),spans=sum(len(event['spans']) for event in offered['events']))
        finally:
            observations.setdefault(arm,{})['cleanup']=session.close()
    assert observations['B']['parent_sha256']==observations['C']['parent_sha256']
    save(AREA/(tag+'.json'),dict(arms=observations,model_calls=0,prefix_reexecuted=False))
    print(observations,flush=True)


def campaign_history():
    old=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')
    snapshot=read(old/'wave-0-ledger.json')['snapshot']
    files=[old/'wave-0-ledger.json',old/'wave-0/worker-result.json']
    elapsed=read(old/'wave-0/worker-result.json')['wall_seconds']
    for path in (Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1'),PRIOR):
        value=read(path/'result.json')['ledger']
        assert not value['inflight'] and not (set(snapshot['arms'])&set(value['arms']))
        assert not (set(snapshot['response_ids'])&set(value['response_ids']))
        snapshot['arms'].update(value['arms'])
        snapshot['response_ids'].extend(value['response_ids'])
        for key in ('tokens','responses'):
            snapshot['study'][key]+=value['study'][key]
        snapshot['study']['uncertain'] |= value['study']['uncertain']
        elapsed+=(path/'result.json').stat().st_mtime-(path/'registration.json').stat().st_mtime
        files.extend([path/'result.json',path/'registration.json'])
    micro=Path('D:/agent-task-runs/wsc-browser-model-route-20261025-v1/result.json')
    probe=read(micro)['phase']
    ids=[row['response_id'] for row in probe['receipts']['response_receipts']]
    assert not (set(ids)&set(snapshot['response_ids']))
    snapshot['arms']['browser/protocol']=dict(started=0,tokens=probe['receipts']['all_usage']['total_tokens'],responses=len(ids),
        limits=dict(max_total_tokens=160000,max_responses=4,max_seconds=90))
    snapshot['response_ids'].extend(ids)
    snapshot['study']['tokens']+=probe['receipts']['all_usage']['total_tokens']
    snapshot['study']['responses']+=len(ids)
    snapshot['study']['uncertain']=True
    elapsed+=probe['seconds']
    files.append(micro)
    protocol=[]
    for name in ('wsc-native-application-phase-20261025-v1','wsc-live-boundary-qualification-20261025-v1','wsc-live-boundary-completion-20261025-v2'):
        path=Path('D:/agent-task-runs')/name/'result.json'
        value=read(path)
        protocol.extend(value['phases'] if 'phases' in value else [value['phase']])
        files.append(path)
    elapsed+=sum(phase['seconds'] for phase in protocol)
    for name in ('wsc-application-matrix-20261025-v2','wsc-a3-qualification-20261025-v2'):
        path=Path('D:/agent-task-runs')/name
        if name.startswith('wsc-application'):
            elapsed+=read(path/'wave-0/worker-result.json')['wall_seconds']
            files.append(path/'wave-0/worker-result.json')
        else:
            assert read(path/'result.json')['ledger']['study']['tokens']==0
            elapsed+=(path/'result.json').stat().st_mtime-(path/'registration.json').stat().st_mtime
            files.append(path/'result.json')
    envelope=qualification_envelope(snapshot,protocol,elapsed)
    return envelope,{str(path):file_hash(path) for path in files}


def register():
    prepared=read(AREA/'staged/prepared.json')
    assert all(file_hash(path)==value for path,value in prepared['payload_files'].items())
    assert file_hash(prepared['capsule'])==prepared['capsule_sha256']
    ready=read(AREA/'preflight-wire.json')
    assert ready['model_calls']==0 and all(row['cleanup']['empty_confirmed'] for row in ready['arms'].values())
    assert ready['arms']['B']['parent_sha256']==ready['arms']['C']['parent_sha256']
    envelope,history_files=campaign_history()
    prepared['envelope'],prepared['history_files']=envelope,history_files
    prepared['pins']={str(path):file_hash(path) for folder in ('src','experiments') for path in sorted((ROOT/folder).rglob('*.py'))}
    prepared['pins'][str(Path(__file__).resolve())]=file_hash(__file__)
    prepared['scope']='One matched continuation pair from shared S2; not whole from-zero task cost or completed 5x3 study'
    prepared['automatic_retries']=0
    save(AREA/'registration.json',prepared)
    print(dict(status='registered',remaining=envelope['remaining_limits'],shared_prefix_reexecuted=False),flush=True)


def run():
    reg=read(AREA/'registration.json')
    assert all(file_hash(path)==value for path,value in reg['pins'].items())
    assert all(file_hash(path)==value for path,value in {**reg['payload_files'],**reg['history_files']}.items())
    budget=StudyBudget({job['pair_id']+'/'+job['arm']:reg['conditions']['budgets']['per_arm'] for job in reg['jobs']},reg['envelope']['remaining_limits'])
    admission=PairedAdmission(AREA/'admission')
    adapters=FrozenApplicationAdapters(reg['conditions'],reg['tasks'],reg['expected_checks'],node_executable=reg['node_executable'])
    def prepared(job):
        path=AREA/'staged'/('payload-'+job['arm']+'.json')
        assert file_hash(path)==reg['payload_files'][str(path)]
        value=read(path)
        save(Path(job['resources']['output'])/'prepared-input.json',dict(payload=str(path),payload_sha256=file_hash(path),
            prefix_capsule=reg['capsule'],prefix_capsule_sha256=reg['capsule_sha256']))
        return value
    def grade(job,index,destination):
        assert manifest(AREA/'staged/frozen-workspace')==read(reg['capsule'])['source_manifest'],'shared_template_changed'
        return adapters.grade(job,index,destination)
    worker=ApplicationStudyWorker(reg['conditions'],budget,prepared,admission,grade)
    def invoke(job):
        def record(phase):
            path=AREA/'phase-journal'/job['arm']
            index=len(list(path.glob('*.json'))) if path.exists() else 0
            save(path/f'{index:03d}.json',phase)
        return worker(job,record)
    outcomes={}
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(invoke,job):job for job in reg['jobs']}
        for future in as_completed(futures):
            job=futures[future]
            try:
                outcomes[job['arm']]=future.result()
            except Exception as error:
                phases=[read(path) for path in sorted((AREA/'phase-journal'/job['arm']).glob('*.json'))]
                budget.mark_unknown(job['pair_id']+'/'+job['arm'],[receipt for phase in phases for receipt in phase.get('receipts',{}).get('response_receipts',[])])
                outcomes[job['arm']]=dict(state='infrastructure_error',phases=phases,error=type(error).__name__+':'+str(error))
            print(job['arm'],outcomes[job['arm']]['state'],outcomes[job['arm']].get('error'),outcomes[job['arm']].get('reason'),flush=True)
    save(AREA/'result.json',dict(outcomes=outcomes,ledger=budget.snapshot(),wall_seconds=time.monotonic()-started,
        historical_envelope=reg['envelope'],prefix_cost_charged_once_in_history=True,
        whole_campaign_usage_complete=False,scope=reg['scope']))
    print(dict(status='finished_review_pending',ledger=budget.snapshot()['study']),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'preflight':preflight,'register':register,'run':run}[sys.argv[1]]()
