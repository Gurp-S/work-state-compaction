"""Paired single-boundary black-box group using real native/WSC transports.

One group selects one authored case/checkpoint. Repetitions run concurrently;
queries touch disposable siblings only. This is not a multicycle runner.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from hashlib import sha256
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import save,read,file_hash,manifest,state
from native_rollout_snapshot import capture_rollout,parse_rollout
from native_recursive_fork import observe
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_incremental_candidate import prepare,frontier,admit_rendered,POLICY
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_blackbox_sessions import fresh,verify_material
from blackbox_resource_probe import verify_paths
from native_host_controls import bootstrap_items
from wsc import WSC,Store
from wsc.resource_io import ResourceIO
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from dataset import canonical,seal
from blackbox_matrix_cases import build,material,CASES
from blackbox import score_answer,questions,compression_evidence
from blackbox_budget import close as close_budget


def answer_schema():
    record=dict(type='object',properties=dict(tested_version=dict(type='string'),artifact_id=dict(type='string')),
        required=['tested_version','artifact_id'],additionalProperties=False)
    value=dict(anyOf=[dict(type=t) for t in ('string','integer','boolean','null')]+[record])
    item=dict(type='object',properties=dict(question_id=dict(type='string'),value=value),required=['question_id','value'],additionalProperties=False)
    return dict(type='object',properties=dict(answers=dict(type='array',items=item)),required=['answers'],additionalProperties=False)


def fork_registration(reg,parent):
    opened=parent.opened['thread'];paths={**parent.registration.get('parent_paths',{}),opened['id']:opened['path']}
    return {**reg,'parent_thread_id':opened['id'],'parent_paths':paths}


def guard_trunk(parent,expected_hash):
    if file_hash(parent.opened['thread']['path'])!=expected_hash:raise ValueError('query_or_transform_mutated_source_trunk')


def compare_histories(histories,workspace):
    raw=[seal(items) for items in histories]
    normalized=[seal(bootstrap_items(items,workspace)) for items in histories]
    if len(set(normalized))!=1:raise ValueError('pre_transform_histories_differ')
    return dict(raw_sha256=raw,normalized_sha256=normalized[0],
        normalization='Existing native_host_controls.bootstrap_items: message/tool transport IDs, message metadata and workspace spelling only.')


def effective(session,raw):
    return observe(raw,session.fork_binding,allow_local_append=True)['items'] if hasattr(session,'fork_binding') else state(parse_rollout(raw).rows)


def import_receiver(session,items,bootstrap,destination):
    path=Path(session.opened['thread']['path']);before=path.read_bytes()
    compare_histories([effective(session,before),bootstrap],session.registration['workspace'])
    response=session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=items))
    snap=capture_rollout(path,archive=Path(destination)/'after-import.jsonl')
    if not path.read_bytes().startswith(before) or not snap.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snap.rows):raise ValueError('receiver_import_changed_or_paid')
    proof=verify_material(effective(session,path.read_bytes()),bootstrap,items,workspace=session.registration['workspace'])
    save(Path(destination)/'native-import.json',dict(response=response,proof=proof))
    return proof


def cold_entries(package):
    entries=[]
    def collect(value):
        if isinstance(value,dict):
            for p,h in (('file_path','sha256'),('readable_path','readable_sha256')):
                if p in value and h in value:entries.append(dict(path=value[p],sha256=value[h]))
            for nested in value.values():collect(nested)
        elif isinstance(value,list):
            for nested in value:collect(nested)
    collect(package)
    entries.extend(dict(path=package[k],sha256=package[k+'_sha256']) for k in ('source_index','understanding_index'))
    return entries


class Cell:
    def __init__(self,base,out,public,point,ledger,repetition,execute,bootstrap_parent):
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=False)
        self.work=self.out/'public-workspace';self.work.mkdir()
        self.reg={**base,'workspace':str(self.work),'sandbox':'read-only','initial_manifest':manifest(self.work),
            'native_cleanup_terminal_observation':True}
        for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):self.reg.pop(key,None)
        self.public,self.point,self.ledger,self.repetition,self.execute=public,point,ledger,repetition,execute
        self.bootstrap_parent=bootstrap_parent
        self.sessions={};self.phases={};self.session_arms={};self.operation=None;self.result=dict(status='started',scores={})
    def new(self,name,parent=None):
        parent=parent or self.bootstrap_parent
        session=NativeForkSession(fork_registration(self.reg,parent),self.out/(name+'-session'))
        self.sessions[name]=session
        session.open()
        self.sessions[name]=session
        return session
    def phase(self,session_name,arm,name,request,*,compact=False,schema=None):
        if not self.execute:raise ValueError('admission_cannot_dispatch_model')
        arm=f'R{self.repetition:02d}/{arm}';self.session_arms[session_name]=arm
        ticket,grant=self.ledger.reserve(arm,dict(max_total_tokens=200000,max_responses=4,max_seconds=240))
        def record(value):
            self.phases[name]=value
            save(self.out/(name+'-settlement.json'),self.ledger.settle(ticket,value))
        phase=self.sessions[session_name].execute_stage(request,self.out/name,grant,record,compact=compact,output_schema=schema)
        if not phase.get('completed') or phase.get('failure') or not phase.get('usage_complete'):raise ValueError('phase_failed:'+name)
        return phase
    def probe(self,name,parent,query,arm):
        before=file_hash(parent.opened['thread']['path']);session=self.new(name,parent)
        phase=self.phase(name,arm,name,query,schema=answer_schema())
        guard_trunk(parent,before)
        if len(phase.get('finals',[]))!=1:raise ValueError('answer_not_unique:'+name)
        return phase['finals'][0]['text']
    def run(self):
        begin=time.monotonic()
        # Authoritative oracle is held only by the coordinator, never by this cell.
        items=material(self.public,self.point)
        self.result.update(items_sha256=seal(items),raw_public_bytes=len(canonical(items).encode()),model_calls=0)
        try:
            parent=self.new('parent');path=Path(parent.opened['thread']['path'])
            parent.server.call('thread/inject_items',dict(threadId=parent.opened['thread']['id'],items=items))
            snap=capture_rollout(path,archive=self.out/'raw-parent.jsonl')
            actual=effective(parent,path.read_bytes());bootstrap=actual[:-len(items)]
            proof=verify_material(actual,bootstrap,items,workspace=str(self.work));save(self.out/'parent-import.json',proof)
            if any(r['type']=='token_usage_record' for r in snap.rows):raise ValueError('parent_inference_observed')
            trunk_hash=file_hash(path)
            native=self.new('native',parent);raw_probe=self.new('raw-admission',parent)
            histories=[observe(Path(s.opened['thread']['path']).read_bytes(),s.fork_binding)['items'] for s in (native,raw_probe)]
            history_proof=compare_histories(histories,str(self.work));save(self.out/'same-history.json',history_proof)
            selector=self.new('selection');receiver=self.new('wsc-receiver')
            compare_histories([effective(selector,Path(selector.opened['thread']['path']).read_bytes()),bootstrap],str(self.work))
            compare_histories([effective(receiver,Path(receiver.opened['thread']['path']).read_bytes()),bootstrap],str(self.work))
            core=WSC(Store(self.out/'state.db',session_id=self.out.name,workspace=str(self.work)),access=lambda *a:True,
                resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
            self.core=core
            from wsc.adapters.codex import CodexCheckpointAdapter
            core.ingest(CodexCheckpointAdapter().import_items(items,thread_id=parent.opened['thread']['id'],start_ordinal=len(bootstrap)))
            snapshot=core.capture()
            # Preflight validates real policy limits before the first paid call.
            _,offered=frontier(core,snapshot,None,self.out/'cold-public')
            verify_paths(selector,[dict(path=e['cold_source']['path'],sha256=e['cold_source']['sha256']) for e in offered['events']],self.out/'preflight-cold-access.json')
            if getattr(self,'compact_wire',False):
                from native_selection_wire import project
                from native_span_handles import project as span_project
                short,_=span_project(offered);projected,_,_=project(short,self.out/'preflight-resource-manifest.json')
                locator=projected['cold_source_manifest']
                verify_paths(selector,[dict(path=locator['path'],sha256=locator['sha256'])],self.out/'preflight-manifest-access.json')
            self.result.update(offered_bytes=len(canonical(offered).encode()),same_history_verified=True,
                normalized_bootstrap_sha256=seal(bootstrap_items(bootstrap,str(self.work))))
            save(self.out/'preflight.json',self.result)
            if not self.execute:
                guard_trunk(parent,trunk_hash);self.result.update(status='admission_passed',model_calls=0)
                return self.result
            limits=parent.server.call('account/rateLimits/read',{})['rateLimits']
            if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
            # Query strings arrive only after compressor-input preflight. They never
            # enter either source trunk or the selector request.
            query=self.query
            raw_phase=self.phase('raw-admission','uncompressed','uncompressed-probe',query,schema=answer_schema())
            if len(raw_phase.get('finals',[]))!=1:raise ValueError('answer_not_unique:uncompressed')
            raw_answer=raw_phase['finals'][0]['text'];guard_trunk(parent,trunk_hash)
            before=Path(native.opened['thread']['path']).read_bytes()
            compact=self.phase('native','native','native-compression','explicit idle compression',compact=True)
            after=(self.out/'native-compression/rollout.jsonl').read_bytes()
            events=[json.loads(s) for s in (self.out/'native-compression/events.jsonl').read_text(encoding='utf-8').splitlines()]
            evidence=compression_evidence(before,after,compact,events);save(self.out/'compression-proof.json',evidence)
            if not evidence['confirmed']:raise ValueError('native_compression_not_confirmed')
            def selected(value):
                verify_paths(selector,[dict(path=e['cold_source']['path'],sha256=e['cold_source']['sha256']) for e in value['events']],self.out/'selector-cold-access.json')
                def execute(request,schema):
                    locator=request['material'].get('cold_source_manifest')
                    if locator:verify_paths(selector,[dict(path=locator['path'],sha256=locator['sha256'])],self.out/'selection-manifest-access.json')
                    phase=self.phase('selection','wsc','selection-phase',canonical(request),schema=schema)
                    return phase,self.out/'selection-phase/rollout.jsonl'
                return generate(value,execute,self.out/'generation',short_span_handles=True,compact_wire=getattr(self,'compact_wire',False))
            prepared=prepare(core,snapshot,None,self.out/'cold-public',selected,source_projection=MODE)
            op=core.stage(prepared['view'],directory=self.out/'exports',archive_directory=self.out/'cold-objects',adapter=IndexedCheckpointAdapter());self.operation=op
            package=admit_rendered(core.package(op));check_evidence(core,package)
            save(self.out/'package.json',package);save(self.out/'continuation.json',prepared['continuation'])
            import_receiver(receiver,package['items'],bootstrap,self.out/'wsc-receiver-session')
            verify_paths(receiver,cold_entries(package),self.out/'receiver-cold-access.json')
            core.discard(op);self.operation=None
            native_answer=self.probe('native-probe',native,query,'native')
            wsc_answer=self.probe('wsc-probe',receiver,query,'wsc')
            guard_trunk(parent,trunk_hash)
            self.result.update(status='completed',answers=dict(uncompressed=raw_answer,native=native_answer,wsc=wsc_answer),
                native_compression_confirmed=True,wsc_package_bytes=len(canonical(package['items']).encode()),
                atomic_core_install_claimed=False,model_directed_recovery_proven=False,
                native_context_tokens=None,wsc_context_tokens=None,
                persisted_wsc_bytes=sum(p.stat().st_size for folder in ('cold-public','cold-objects','exports') for p in (self.out/folder).rglob('*') if p.is_file()))
        except Exception as error:self.result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            cleanup={}
            for name,session in self.sessions.items():
                try:cleanup[name]=session.close()
                except Exception as error:cleanup[name]=dict(empty_confirmed=False,error=str(error))
            self.result['cleanup']=cleanup
            if any(v is None or v.get('empty_confirmed') is not True for v in cleanup.values()):self.result.update(status='failed_preserved',cleanup_unknown=True)
            for name,session in self.sessions.items():
                if not session.opened:continue
                snap=capture_rollout(session.opened['thread']['path'],archive=self.out/('closed-'+name+'.jsonl'))
                expected={r['response_id']:r['usage'] for p in self.phases.values() if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
                actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
                if not snap.metadata['exists'] and not expected and name in ('selection','wsc-receiver') and self.result.get('status')!='completed':continue
                if expected!=actual or not snap.metadata['parse_complete']:
                    if name in self.session_arms:self.ledger.mark_unknown(self.session_arms[name])
                    self.result.update(status='failed_preserved',closure_accounting_mismatch=name)
            self.result['model_calls']=sum(len(p.get('receipts',{}).get('response_receipts',[])) for p in self.phases.values())
            self.result['seconds']=time.monotonic()-begin
            save(self.out/'result.json',self.result)
        return self.result


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--case',choices=CASES,default='authority');parser.add_argument('--seed',type=int,default=20261027)
    parser.add_argument('--checkpoint',type=int,default=5);parser.add_argument('--noise',type=int,default=80)
    parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--compact-wire',action='store_true');args=parser.parse_args()
    if args.repeats<3 or args.workers<1 or args.workers>3:parser.error('At least 3 repetitions and 1..3 workers required')
    base=read(args.registration)['sessions']['B'];parent=read(args.parent_envelope)
    if file_hash(base['executable'])!=base['executable_sha256']:raise ValueError('registered_executable_changed')
    public,oracle=build(args.case,args.seed,args.checkpoint,args.noise);point=oracle['checkpoints'][-1]
    caps=dict(max_total_tokens=600000*args.repeats,max_responses=12*args.repeats,max_seconds=1200)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    arm_caps={f'R{r:02d}/{arm}':dict(max_total_tokens=n,max_responses=m,max_seconds=900) for r in range(1,args.repeats+1)
        for arm,n,m in [('uncompressed',100000,2),('native',200000,4),('wsc',300000,6)]}
    args.out.mkdir(parents=True,exist_ok=False);ledger=StudyBudget(arm_caps,caps);begin=time.monotonic()
    save(args.out/'registration.json',dict(kind='single_boundary_group',case=args.case,checkpoint=args.checkpoint,
        repetitions=args.repeats,workers=args.workers,execute=args.execute,limits=caps,arm_limits=arm_caps,
        compact_wire=args.compact_wire,
        public_sha256=seal(public),query_sha256=seal(questions(point)),model=base['model'],effort=base['effort'],
        executable_sha256=base['executable_sha256'],parent_envelope_sha256=file_hash(args.parent_envelope),
        policy=POLICY,automatic_retries=0,old_unknowns_preserved=True,
        oracle_written_only_after_all_sessions_closed=True,
        scope='System black-box, one actual compaction per native repetition; not 5 successive compactions.',
        source_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [*Path(__file__).resolve().parent.glob('*.py'),* (ROOT/'src/wsc').rglob('*.py'),ROOT/'experiments/native_incremental_candidate.py',ROOT/'experiments/native_incremental_generation.py']}))
    save(args.out/'dataset.public.json',public)
    work=args.out/'bootstrap-workspace';work.mkdir()
    bootreg={**base,'workspace':str(work),'sandbox':'read-only','native_cleanup_terminal_observation':True}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):bootreg.pop(key,None)
    bootstrap_parent=fresh(bootreg,args.out/'bootstrap-session');results={}
    try:
        anchor=dict(type='message',role='assistant',content=[dict(type='output_text',text=canonical(dict(record_type='bench.bootstrap/1',id='fixed-runtime-20261027')))])
        bootstrap_parent.server.call('thread/inject_items',dict(threadId=bootstrap_parent.opened['thread']['id'],items=[anchor]))
        snap=capture_rollout(bootstrap_parent.opened['thread']['path'],archive=args.out/'bootstrap.jsonl')
        if not snap.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snap.rows):raise ValueError('bootstrap_unknown_or_paid')
        boot_hash=file_hash(bootstrap_parent.opened['thread']['path'])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending={}
            for repetition in range(1,args.repeats+1):
                cell=Cell(base,args.out/f'R{repetition:02d}',public,args.checkpoint,ledger,repetition,args.execute,bootstrap_parent)
                cell.compact_wire=args.compact_wire
                cell.query=canonical(questions(point));pending[pool.submit(cell.run)]=repetition
            for future in as_completed(pending):
                repetition=pending[future]
                try:results[str(repetition)]=future.result()
                except Exception as error:results[str(repetition)]=dict(status='failed_preserved',error=type(error).__name__+':'+str(error))
                print(canonical(dict(repetition=repetition,status=results[str(repetition)]['status'],error=(results[str(repetition)].get('error') or '')[:240])),flush=True)
        guard_trunk(bootstrap_parent,boot_hash)
    finally:
        bootstrap_cleanup=bootstrap_parent.close();save(args.out/'bootstrap-cleanup.json',bootstrap_cleanup)
    # Oracle and scores are coordinator-only and are saved after runtime teardown.
    save(args.out/'oracle.private.json',oracle)
    for result in results.values():
        result['scores']={arm:score_answer(answer,point) for arm,answer in result.get('answers',{}).items()}
    snapshot=ledger.snapshot();elapsed=time.monotonic()-begin
    result=dict(status='completed' if bootstrap_cleanup.get('empty_confirmed') and len(results)==args.repeats and all(r['status']==('completed' if args.execute else 'admission_passed') for r in results.values()) else 'failed_preserved',
        execute=args.execute,repetitions=results,ledger=snapshot,seconds=elapsed,summary_content_inspected=False,
        model_randomness_not_eliminated=True,whole_campaign_usage_complete=False)
    save(args.out/'result.json',result)
    if args.execute and not snapshot['inflight']:
        save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,snapshot,elapsed),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],tokens=snapshot['study']['tokens'],responses=snapshot['study']['responses'],seconds=elapsed)),flush=True)


if __name__=='__main__':main()
