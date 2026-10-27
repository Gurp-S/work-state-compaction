"""Finish never-dispatched WSC arms and unqueried native siblings; no recompaction."""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,json,time
from blackbox_group_runner import (Cell,effective,fork_registration,compare_histories,import_receiver,
    answer_schema,cold_entries,guard_trunk,ROOT)
from blackbox_resource_probe import verify_paths
from native_evidence import read,save,file_hash,manifest
from native_rollout_snapshot import capture_rollout
from native_application_budget import StudyBudget
from native_incremental_candidate import frontier,prepare,admit_rendered
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from wsc import WSC,Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.resource_io import ResourceIO
from wsc.publication import check_evidence
from wsc.source_reference_view import MODE
from blackbox_matrix_cases import build,material
from blackbox import questions,score_answer
from dataset import canonical,seal
from blackbox_budget import close as close_budget


class ResumeCell(Cell):
    def run(self):
        begin=time.monotonic();source=self.source;old=read(source/'result.json')
        items=material(self.public,self.point)
        self.result.update(items_sha256=seal(items),raw_public_bytes=len(canonical(items).encode()),reused_source=str(source))
        try:
            if old['status']!='failed_preserved' or old.get('model_calls')!=2:raise ValueError('source_not_expected_partial_group')
            if any(c.get('empty_confirmed') is not True for c in old['cleanup'].values()):raise ValueError('source_cleanup_unknown')
            if (source/'selection-phase').exists():raise ValueError('selection_already_dispatched')
            proof=read(source/'compression-proof.json')
            if not proof.get('confirmed'):raise ValueError('source_compression_not_confirmed')
            compact=read(source/'native-compression/phase-outcome.json');baseline=read(source/'uncompressed-probe/phase-outcome.json')
            if any(not p.get('usage_complete') or not p.get('completed') or p.get('failure') for p in (compact,baseline)):raise ValueError('source_phases_not_closed')
            if len(baseline.get('finals',[]))!=1:raise ValueError('source_answer_not_unique')
            opened=read(source/'native-session/thread-fork.json')
            native_parent=SimpleNamespace(opened=opened,registration=read(source/'native-session/registration.json'))
            if file_hash(opened['thread']['path'])!=file_hash(source/'closed-native.jsonl'):raise ValueError('source_native_parent_changed')
            if file_hash(source/'native-compression/rollout.jsonl')!=proof['after_sha256']:raise ValueError('source_compaction_archive_changed')
            rawparent=SimpleNamespace(opened=read(source/'parent-session/thread-fork.json'),
                fork_binding=read(source/'parent-session/ancestry/binding.json'))
            raw=Path(rawparent.opened['thread']['path']).read_bytes()
            if file_hash(rawparent.opened['thread']['path'])!=file_hash(source/'closed-parent.jsonl'):raise ValueError('source_business_parent_changed')
            bootstrap=effective(rawparent,raw)[:-len(items)]
            from native_blackbox_sessions import verify_material
            verify_material(effective(rawparent,raw),bootstrap,items,workspace=str(self.work))
            selector=self.new('selection');receiver=self.new('wsc-receiver')
            compare_histories([effective(selector,Path(selector.opened['thread']['path']).read_bytes()),bootstrap],str(self.work))
            compare_histories([effective(receiver,Path(receiver.opened['thread']['path']).read_bytes()),bootstrap],str(self.work))
            self.core=WSC(Store(self.out/'state.db',session_id=self.out.name,workspace=str(self.work)),access=lambda *a:True,
                resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
            self.core.ingest(CodexCheckpointAdapter().import_items(items,thread_id=rawparent.opened['thread']['id'],start_ordinal=len(bootstrap)))
            snapshot=self.core.capture();_,offered=frontier(self.core,snapshot,None,self.out/'cold-public')
            verify_paths(selector,[dict(path=e['cold_source']['path'],sha256=e['cold_source']['sha256']) for e in offered['events']],self.out/'preflight-cold-access.json')
            if getattr(self,'compact_wire',False):
                from native_selection_wire import project
                from native_span_handles import project as span_project
                short,_=span_project(offered)
                projected,_,_=project(short,self.out/'preflight-resource-manifest.json')
                locator=projected['cold_source_manifest']
                verify_paths(selector,[dict(path=locator['path'],sha256=locator['sha256'])],self.out/'preflight-manifest-access.json')
            self.result.update(same_history_verified=True,offered_bytes=len(canonical(offered).encode()),reused_native_compression=True,
                reused_uncompressed_query=True,native_compaction_calls=0)
            save(self.out/'preflight.json',self.result)
            if not self.execute:
                self.result.update(status='admission_passed');return self.result
            limits=selector.server.call('account/rateLimits/read',{})['rateLimits']
            if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
            def selected(value):
                def execute(request,schema):
                    locator=request['material'].get('cold_source_manifest')
                    if locator:verify_paths(selector,[dict(path=locator['path'],sha256=locator['sha256'])],self.out/'selection-manifest-access.json')
                    phase=self.phase('selection','wsc','selection-phase',canonical(request),schema=schema)
                    return phase,self.out/'selection-phase/rollout.jsonl'
                return generate(value,execute,self.out/'generation',short_span_handles=True,compact_wire=getattr(self,'compact_wire',False))
            prepared=prepare(self.core,snapshot,None,self.out/'cold-public',selected,source_projection=MODE)
            op=self.core.stage(prepared['view'],directory=self.out/'exports',archive_directory=self.out/'cold-objects',adapter=IndexedCheckpointAdapter());self.operation=op
            package=admit_rendered(self.core.package(op));check_evidence(self.core,package)
            save(self.out/'package.json',package);save(self.out/'continuation.json',prepared['continuation'])
            import_receiver(receiver,package['items'],bootstrap,self.out/'wsc-receiver-session')
            verify_paths(receiver,cold_entries(package),self.out/'receiver-cold-access.json')
            self.core.discard(op);self.operation=None
            if getattr(self,'native_reference',None):
                reference=self.native_reference/'native-probe'
                phase=read(reference/'phase-outcome.json');attempt=read(reference/'attempt.json')
                session_reg=read(self.native_reference/'native-probe-session/registration.json')
                if not phase.get('completed') or not phase.get('usage_complete') or phase.get('failure') or len(phase.get('finals',[]))!=1:raise ValueError('native_reference_incomplete')
                if attempt['request']!=self.query or session_reg['parent_thread_id']!=native_parent.opened['thread']['id']:raise ValueError('native_reference_query_or_parent_changed')
                if any(session_reg[key]!=self.reg[key] for key in ('model','effort','executable_sha256')):raise ValueError('native_reference_actor_changed')
                native_answer=phase['finals'][0]['text'];save(self.out/'reused-native-query.json',dict(source=str(reference),phase_sha256=file_hash(reference/'phase-outcome.json')))
            else:native_answer=self.probe('native-probe',native_parent,self.query,'native')
            wsc_answer=self.probe('wsc-probe',receiver,self.query,'wsc')
            guard_trunk(native_parent,file_hash(source/'closed-native.jsonl'))
            self.result.update(status='completed',answers=dict(uncompressed=baseline['finals'][0]['text'],native=native_answer,wsc=wsc_answer),
                native_compression_confirmed=True,wsc_package_bytes=len(canonical(package['items']).encode()),
                atomic_core_install_claimed=False,model_directed_recovery_proven=False,
                persisted_wsc_bytes=sum(p.stat().st_size for folder in ('cold-public','cold-objects','exports') for p in (self.out/folder).rglob('*') if p.is_file()))
        except Exception as error:self.result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            self.result['cleanup']={name:session.close() for name,session in self.sessions.items()}
            if any(v.get('empty_confirmed') is not True for v in self.result['cleanup'].values()):self.result.update(status='failed_preserved',cleanup_unknown=True)
            for name,session in self.sessions.items():
                if not session.opened:continue
                snap=capture_rollout(session.opened['thread']['path'],archive=self.out/('closed-'+name+'.jsonl'))
                expected={r['response_id']:r['usage'] for p in self.phases.values() if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
                actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
                if expected!=actual or not snap.metadata['parse_complete']:
                    if name in self.session_arms:self.ledger.mark_unknown(self.session_arms[name])
                    self.result.update(status='failed_preserved',closure_accounting_mismatch=name)
            self.result['model_calls']=sum(len(p.get('receipts',{}).get('response_receipts',[])) for p in self.phases.values())
            self.result['seconds']=time.monotonic()-begin;save(self.out/'result.json',self.result)
        return self.result


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','source','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--compact-wire',action='store_true')
    parser.add_argument('--compare-completed',type=Path)
    parser.add_argument('--parent-envelope',type=Path)
    args=parser.parse_args()
    old=read(args.source/'result.json');reg=read(args.source/'registration.json');base=read(args.registration)['sessions']['B']
    if old['ledger']['study']['uncertain'] or old['ledger']['inflight']:raise ValueError('source_accounting_not_closed')
    if file_hash(base['executable'])!=reg['executable_sha256']:raise ValueError('native_executable_changed')
    envelope=args.parent_envelope or args.source/'next-admission-envelope.json'
    parent=read(envelope)
    reference=None
    if args.compare_completed:
        if not args.parent_envelope:raise ValueError('explicit_latest_envelope_required_for_variant')
        reference=read(args.compare_completed/'result.json')
        if reference['status']!='completed' or reference['ledger']['study']['uncertain'] or reference['ledger']['inflight']:raise ValueError('reference_not_closed')
        if reference.get('reused_group')!=str(args.source):raise ValueError('reference_source_changed')
    public=read(args.source/'dataset.public.json');rebuilt,oracle=build(reg['case'],public['seed'],reg['checkpoint'],len([e for e in public['events'] if e['record']['record_type']=='bench.noise/1'])//reg['checkpoint'])
    if seal(public)!=reg['public_sha256'] or public!=rebuilt:raise ValueError('public_fixture_changed')
    point=oracle['checkpoints'][-1];query=canonical(questions(point))
    if seal(questions(point))!=reg['query_sha256']:raise ValueError('query_changed')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    caps=dict(max_total_tokens=1200000,max_responses=24,max_seconds=900)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    arms={f'R{r:02d}/{arm}':dict(max_total_tokens=n,max_responses=m,max_seconds=800) for r in (1,2,3) for arm,n,m in [('native',100000,2),('wsc',300000,6)]}
    ledger=StudyBudget(arms,caps)
    boot=SimpleNamespace(opened=read(args.source/'bootstrap-session/opened.json'),registration=read(args.source/'bootstrap-session/registration.json') if (args.source/'bootstrap-session/registration.json').exists() else {})
    # fresh() does not persist registration; this empty ancestry map is correct
    # for the original root, whose session_meta has no history_base.
    save(args.out/'registration.json',dict(reused_group=str(args.source),source_result_sha256=file_hash(args.source/'result.json'),
        parent_envelope_sha256=file_hash(envelope),limits=caps,arm_limits=arms,execute=args.execute,
        compact_wire=args.compact_wire,reused_native_post_group=str(args.compare_completed) if args.compare_completed else None,
        regenerated_native_compactions=0,rerun_uncompressed_queries=0,old_failures_preserved=True,automatic_retries=0,
        source_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in Path(__file__).resolve().parent.glob('*.py')}))
    results={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={}
        for r in (1,2,3):
            cell=ResumeCell(base,args.out/f'R{r:02d}',public,reg['checkpoint'],ledger,r,args.execute,boot)
            cell.compact_wire=args.compact_wire
            cell.native_reference=args.compare_completed/f'R{r:02d}' if args.compare_completed else None
            cell.source=args.source/f'R{r:02d}';cell.work=cell.source/'public-workspace';cell.reg.update(workspace=str(cell.work),initial_manifest=manifest(cell.work));cell.query=query
            futures[pool.submit(cell.run)]=r
        for future in as_completed(futures):
            r=futures[future]
            try:results[str(r)]=future.result()
            except Exception as error:results[str(r)]=dict(status='failed_preserved',error=str(error))
            print(canonical(dict(repetition=r,status=results[str(r)]['status'],error=(results[str(r)].get('error') or '')[:240])),flush=True)
    save(args.out/'oracle.private.json',oracle)
    for result in results.values():result['scores']={arm:score_answer(answer,point) for arm,answer in result.get('answers',{}).items()}
    snapshot=ledger.snapshot();elapsed=time.monotonic()-begin
    reused_native_phases=[read(args.compare_completed/f'R{r:02d}/native-probe/phase-outcome.json') for r in (1,2,3)] if reference else []
    reused_extra_tokens=sum(p['receipts']['all_usage']['total_tokens'] for p in reused_native_phases)
    reused_extra_responses=sum(len(p['receipts']['response_receipts']) for p in reused_native_phases)
    result=dict(status='completed' if all(r['status']==('completed' if args.execute else 'admission_passed') for r in results.values()) else 'failed_preserved',
        repetitions=results,ledger=snapshot,seconds=elapsed,execute=args.execute,reused_group=str(args.source),
        reused_tokens=old['ledger']['study']['tokens']+reused_extra_tokens,reused_responses=old['ledger']['study']['responses']+reused_extra_responses,
        reused_native_post_group=str(args.compare_completed) if args.compare_completed else None,whole_campaign_usage_complete=False)
    save(args.out/'result.json',result)
    if args.execute and not snapshot['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,snapshot,elapsed),parent_envelope=str(envelope),parent_envelope_sha256=file_hash(envelope)))
    print(canonical(dict(status=result['status'],new_tokens=snapshot['study']['tokens'],new_responses=snapshot['study']['responses'],seconds=elapsed)),flush=True)


if __name__=='__main__':main()
