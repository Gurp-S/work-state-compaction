"""Two real boundaries and a later release-audit task; no semantic judge."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,json,time
from blackbox_group_runner import (Cell,ROOT,effective,compare_histories,import_receiver,cold_entries,
    guard_trunk,answer_schema)
from blackbox_resource_probe import verify_paths
from blackbox_recovery_case import build,tool_recovery_evidence,message
from native_evidence import read,save,file_hash,manifest
from native_rollout_snapshot import capture_rollout
from native_application_budget import StudyBudget
from native_incremental_candidate import frontier,prepare,admit_rendered,POLICY
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_blackbox_sessions import fresh,verify_material
from native_selection_wire import project
from native_span_handles import project as project_spans
from wsc import WSC,Store,Selection
from wsc.resource_io import ResourceIO
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from blackbox import questions,score_answer,compression_evidence
from blackbox_budget import close as close_budget
from dataset import canonical,seal


def append_history(session,items,destination):
    path=Path(session.opened['thread']['path']);before=path.read_bytes();prior=effective(session,before)
    response=session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=items))
    after=path.read_bytes()
    if not after.startswith(before):raise ValueError('append_changed_source_prefix')
    proof=verify_material(effective(session,after),prior,items,workspace=session.registration['workspace'])
    save(destination,dict(response=response,proof=proof,before_sha256=seal(prior),after_sha256=seal(effective(session,after))))


class RecoveryCell(Cell):
    def compact(self,number):
        session=self.sessions['native'];before=Path(session.opened['thread']['path']).read_bytes();name=f'B{number}-compression'
        phase=self.phase('native','native',name,'explicit idle compression',compact=True)
        events=[json.loads(s) for s in (self.out/name/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        proof=compression_evidence(before,(self.out/name/'rollout.jsonl').read_bytes(),phase,events)
        save(self.out/(name+'-proof.json'),proof)
        if not proof['confirmed']:raise ValueError('native_compression_unconfirmed')
    def preflight(self,core,snapshot,previous,number,selector):
        _,offered=frontier(core,snapshot,previous,self.out/'cold-public')
        verify_paths(selector,[dict(path=e['cold_source']['path'],sha256=e['cold_source']['sha256']) for e in offered['events']],self.out/f'C{number}-cold-access.json')
        short,_=project_spans(offered);wire,_,_=project(short,self.out/f'C{number}-preflight-manifest.json')
        loc=wire['cold_source_manifest'];verify_paths(selector,[dict(path=loc['path'],sha256=loc['sha256'])],self.out/f'C{number}-manifest-access.json')
        return offered
    def select(self,core,snapshot,previous,number,selector,offered):
        if not self.execute:
            # Mechanical gate only; not a WSC model score or native comparison.
            view=core.prepare(snapshot,Selection(),producer='zero-model-preflight',source_projection=MODE)
            return dict(view=view,continuation=dict(session_id=snapshot.session_id,workspace=snapshot.workspace,
                cut=snapshot.cut,source_digest=snapshot.source_digest,understanding_refs=[],excerpts=[],view_id=view,policy=POLICY['id']))
        def selected(value):
            def execute(request,schema):
                if number==2:
                    # Exposure diagnostic, never the answer scorer.
                    self.result['target_nonce_literal_in_second_selector_input']=self.target['nonce'] in canonical(request)
                locator=request['material']['cold_source_manifest']
                verify_paths(selector,[dict(path=locator['path'],sha256=locator['sha256'])],self.out/f'C{number}-selection-manifest-access.json')
                phase=self.phase(f'selector-{number}','wsc',f'C{number}-selection',canonical(request),schema=schema)
                return phase,self.out/f'C{number}-selection/rollout.jsonl'
            return generate(value,execute,self.out/f'C{number}-generation',short_span_handles=True,compact_wire=True)
        return prepare(core,snapshot,previous,self.out/'cold-public',selected,source_projection=MODE)
    def publish(self,core,prepared,number,receiver,bootstrap):
        op=core.stage(prepared['view'],directory=self.out/f'C{number}-exports',archive_directory=self.out/'cold-objects',adapter=IndexedCheckpointAdapter())
        package=admit_rendered(core.package(op));check_evidence(core,package)
        save(self.out/f'C{number}-package.json',package);save(self.out/f'C{number}-continuation.json',prepared['continuation'])
        import_receiver(receiver,package['items'],bootstrap,self.out/f'receiver-{number}-session')
        verify_paths(receiver,cold_entries(package),self.out/f'C{number}-receiver-access.json')
        core.discard(op)
        return package
    def run(self):
        begin=time.monotonic();prefix=self.public['prefix'];delta=self.public['delta'];self.result.update(public_sha256=seal(self.public))
        try:
            parent=self.new('parent');append_history(parent,prefix,self.out/'prefix-import.json')
            path=Path(parent.opened['thread']['path']);bootstrap=effective(parent,path.read_bytes())[:-len(prefix)]
            native=self.new('native',parent);sibling=self.new('prefix-check',parent)
            compare_histories([effective(s,Path(s.opened['thread']['path']).read_bytes()) for s in (native,sibling)],str(self.work))
            core=WSC(Store(self.out/'state.db',session_id=self.out.name,workspace=str(self.work)),access=lambda *a:True,
                resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1');self.core=core
            from wsc.adapters.codex import CodexCheckpointAdapter
            adapter=CodexCheckpointAdapter();ids=core.ingest(adapter.import_items(prefix,thread_id=parent.opened['thread']['id'],start_ordinal=len(bootstrap)))
            target_id=ids[5]
            first_selector=self.new('selector-1');first_receiver=self.new('receiver-1')
            first_snapshot=core.capture();offered=self.preflight(core,first_snapshot,None,1,first_selector)
            if self.execute:
                if not self.group_quota_admitted:raise ValueError('group_quota_not_admitted')
                self.compact(1)
            first=self.select(core,first_snapshot,None,1,first_selector,offered)
            self.publish(core,first,1,first_receiver,bootstrap)
            # Identical later events enter the three actual system histories.
            append_history(parent,delta,self.out/'raw-delta-import.json')
            append_history(native,delta,self.out/'native-delta-import.json')
            append_history(first_receiver,delta,self.out/'wsc-delta-import.json')
            core.ingest(adapter.import_items(delta,thread_id=parent.opened['thread']['id'],start_ordinal=len(bootstrap)+len(prefix)))
            second_snapshot=core.capture();second_selector=self.new('selector-2');second_receiver=self.new('receiver-2')
            offered2=self.preflight(core,second_snapshot,first['continuation'],2,second_selector)
            old=[e for e in offered2['events'] if e['seq']<=first['continuation']['cut']]
            if any(e['spans'] or e['text_in_frontier'] for e in old):raise ValueError('old_text_unexpectedly_inline')
            target_event=next(e for e in offered2['events'] if e['cold_source']['source_id']==target_id)
            source_object=read(target_event['cold_source']['path'])
            self.result.update(old_source_count=len(old),old_sources_without_inline_spans=True,target_source_id=target_id,
                target_in_old_prefix=target_event['seq']<=first['continuation']['cut'])
            save(self.out/'preflight.json',self.result)
            if not self.execute:self.result.update(status='admission_passed');return self.result
            raw_answer=self.probe('uncompressed-probe',parent,self.query,'uncompressed')
            self.compact(2)
            second=self.select(core,second_snapshot,first['continuation'],2,second_selector,offered2)
            package=self.publish(core,second,2,second_receiver,bootstrap)
            native_answer=self.probe('native-probe',native,self.query,'native')
            wsc_answer=self.probe('wsc-probe',second_receiver,self.query,'wsc')
            manifest2=read(self.out/'C2-generation/resource-manifest.json')
            evidence={}
            for phase_name in ('C2-selection','wsc-probe'):
                snap=capture_rollout(self.out/phase_name/'rollout.jsonl')
                evidence[phase_name]=tool_recovery_evidence(snap.rows,manifest2,source_object,self.target)
            save(self.out/'model-recovery-evidence.json',evidence)
            self.result.update(status='completed',answers=dict(uncompressed=raw_answer,native=native_answer,wsc=wsc_answer),
                native_compactions=2,wsc_generations=2,hot_package_bytes=len(canonical(package['items']).encode()),
                recovery_evidence=evidence,atomic_core_install_claimed=False)
        except Exception as error:self.result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            cleanup={}
            for name,session in self.sessions.items():
                try:cleanup[name]=session.close()
                except Exception as error:cleanup[name]=dict(empty_confirmed=False,error=str(error))
            self.result['cleanup']=cleanup
            if any(v is None or not v.get('empty_confirmed') for v in cleanup.values()):self.result.update(status='failed_preserved',cleanup_unknown=True)
            for name,session in self.sessions.items():
                if not session.opened:continue
                snap=capture_rollout(session.opened['thread']['path'],archive=self.out/('closed-'+name+'.jsonl'))
                expected={r['response_id']:r['usage'] for p in self.phases.values() if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
                actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
                if expected!=actual or not snap.metadata['parse_complete']:
                    if name in self.session_arms:self.ledger.mark_unknown(self.session_arms[name])
                    self.result.update(status='failed_preserved',closure_accounting_mismatch=name)
            self.result['seconds']=time.monotonic()-begin;save(self.out/'result.json',self.result)
        return self.result


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--seed',type=int,default=20261027)
    parser.add_argument('--receipt-count',type=int,default=64);args=parser.parse_args()
    base=read(args.registration)['sessions']['B'];parent_budget=read(args.parent_envelope)
    if file_hash(base['executable'])!=base['executable_sha256']:raise ValueError('registered_executable_changed')
    public,oracle,target=build(args.seed,args.receipt_count);query=canonical(questions(oracle))
    caps=dict(max_total_tokens=1800000,max_responses=54,max_seconds=900)
    if any(caps[k]>parent_budget['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    arms={f'R{r:02d}/{arm}':dict(max_total_tokens=n,max_responses=m,max_seconds=800) for r in (1,2,3)
        for arm,n,m in [('uncompressed',80000,2),('native',160000,6),('wsc',360000,10)]}
    args.out.mkdir(parents=True,exist_ok=False);ledger=StudyBudget(arms,caps);begin=time.monotonic()
    save(args.out/'registration.json',dict(case='release-receipt-recovery',seed=args.seed,receipt_count=args.receipt_count,
        repetitions=3,workers=3,execute=args.execute,limits=caps,arm_limits=arms,public_sha256=seal(public),
        query_sha256=seal(questions(oracle)),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        actor={k:base[k] for k in ('model','effort','executable_sha256')},algorithm_level_comparison=False,
        policy=POLICY,target_predeclared='build-003',automatic_retries=0,oracle_not_in_selector=True,
        source_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [*Path(__file__).resolve().parent.glob('*.py'),ROOT/'experiments/native_selection_wire.py',ROOT/'experiments/native_incremental_generation.py',ROOT/'experiments/native_incremental_candidate.py']}))
    save(args.out/'dataset.public.json',public)
    work=args.out/'bootstrap-workspace';work.mkdir();reg={**base,'workspace':str(work),'sandbox':'read-only','native_cleanup_terminal_observation':True}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    boot=fresh(reg,args.out/'bootstrap-session');results={};coordinator_error=None
    try:
        boot.server.call('thread/inject_items',dict(threadId=boot.opened['thread']['id'],items=[message('assistant',dict(record_type='bench.bootstrap/1',id='recovery-runtime-20261027'))]))
        snapshot=capture_rollout(boot.opened['thread']['path'],archive=args.out/'bootstrap.jsonl')
        if not snapshot.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snapshot.rows):raise ValueError('bootstrap_unknown_or_paid')
        checksum=file_hash(boot.opened['thread']['path'])
        if args.execute:
            quota=boot.server.call('account/rateLimits/read',{})
            save(args.out/'group-rate-limits.json',quota)
            if any(quota['rateLimits'].get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={}
            for r in (1,2,3):
                cell=RecoveryCell(base,args.out/f'R{r:02d}',public,2,ledger,r,args.execute,boot);cell.target=target;cell.query=query
                cell.group_quota_admitted=args.execute
                futures[pool.submit(cell.run)]=r
            for future in as_completed(futures):
                r=futures[future]
                try:results[str(r)]=future.result()
                except Exception as error:results[str(r)]=dict(status='failed_preserved',error=str(error))
                print(canonical(dict(repetition=r,status=results[str(r)]['status'],error=(results[str(r)].get('error') or '')[:240])),flush=True)
        guard_trunk(boot,checksum)
    except Exception as error:coordinator_error=type(error).__name__+':'+str(error)
    finally:save(args.out/'bootstrap-cleanup.json',boot.close())
    save(args.out/'oracle.private.json',oracle)
    for result in results.values():result['scores']={arm:score_answer(answer,oracle) for arm,answer in result.get('answers',{}).items()}
    snapshot=ledger.snapshot();elapsed=time.monotonic()-begin
    result=dict(status='completed' if len(results)==3 and all(r['status']==('completed' if args.execute else 'admission_passed') for r in results.values()) else 'failed_preserved',
        execute=args.execute,repetitions=results,ledger=snapshot,seconds=elapsed,whole_campaign_usage_complete=False)
    result['coordinator_error']=coordinator_error
    save(args.out/'result.json',result)
    if args.execute and not snapshot['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent_budget,snapshot,elapsed),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],tokens=snapshot['study']['tokens'],responses=snapshot['study']['responses'],seconds=elapsed)),flush=True)


if __name__=='__main__':main()
