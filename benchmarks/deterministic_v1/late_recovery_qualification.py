"""Two actual C selections, late recovery and QA; native B is not simulated."""
from pathlib import Path
import argparse,json,time
from blackbox_recovery_runner import RecoveryCell,append_history
from blackbox_group_runner import ROOT,effective,answer_schema
from late_recovery_case import build
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_blackbox_sessions import fresh
from native_selector_runtime import PROFILE
from native_source_tool import SOURCE_TOOL
from native_source_tool_budget import BudgetResultSourceToolHandler
from native_incremental_candidate import prepare,frontier
from native_incremental_generation import generate
from native_application_budget import StudyBudget
from blackbox_minimal_recovery_group import probe_service
from blackbox_budget import close as close_budget
from blackbox import questions,score_answer
from blackbox_recovery_case import message
from dataset import canonical,seal
from wsc import WSC,Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.resource_io import ResourceIO
from wsc.source_reference_view import MODE
from wsc.source_access import SnapshotSourceAccess
from wsc.snapshot_literal_access import SnapshotLiteralAccess


class LateCell(RecoveryCell):
    def accounting_unknown(self):
        self.ledger.mark_unknown(f'R{self.repetition:02d}/wsc')

    def new(self,name,parent=None):
        if not name.startswith('selector-'):return super().new(name,parent)
        session=fresh(self.reg,self.out/(name+'-session'),dynamic_tools=[SOURCE_TOOL],selector_runtime=PROFILE)
        self.sessions[name]=session
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[message('assistant',dict(record_type='source_selection_runtime/1'))]))
        return session

    def phase(self,session_name,arm,name,request,*,compact=False,schema=None,tool_handler=None):
        if not self.execute or compact:raise ValueError('qualification_dispatch_not_admitted')
        slot=f'R{self.repetition:02d}/wsc';self.session_arms[session_name]=slot
        limits=dict(max_total_tokens=200000 if tool_handler else 120000,max_responses=4,max_seconds=240 if tool_handler else 120)
        ticket,grant=self.ledger.reserve(slot,limits)
        def record(value):self.phases[name]=value;save(self.out/(name+'-settlement.json'),self.ledger.settle(ticket,value))
        phase=self.sessions[session_name].execute_stage(request,self.out/name,grant,record,output_schema=schema,tool_handler=tool_handler)
        if not phase['completed'] or phase['failure'] or not phase['usage_complete']:raise ValueError('late_phase_failed:'+name)
        return phase

    def select(self,core,snapshot,previous,number,selector,offered):
        if not self.execute:return super().select(core,snapshot,previous,number,selector,offered)
        handler=BudgetResultSourceToolHandler(SnapshotLiteralAccess(core.store,snapshot,access=core.access))
        def selected(value):
            def execute(request,schema):
                phase=self.phase(f'selector-{number}','wsc',f'C{number}-selection',canonical(request),schema=schema,tool_handler=handler)
                return phase,self.out/f'C{number}-selection/rollout.jsonl'
            return generate(value,execute,self.out/f'C{number}-generation',short_span_handles=True,compact_wire=True,source_access=handler.describe())
        try:return prepare(core,snapshot,previous,self.out/'cold-public',selected,source_projection=MODE)
        finally:
            save(self.out/f'C{number}-tool-trace.json',handler.trace)
            save(self.out/f'C{number}-tool-metrics.json',dict(refused_callbacks=handler.refused_callbacks,rows_verified=handler.reader.rows_verified,text_bytes_examined=handler.reader.text_bytes_examined))

    def run(self):
        begin=time.monotonic();prefix=self.public['prefix'];delta=self.public['delta']
        try:
            parent=self.new('parent');append_history(parent,prefix,self.out/'prefix-import.json')
            bootstrap=effective(parent,Path(parent.opened['thread']['path']).read_bytes())[:-len(prefix)]
            core=WSC(Store(self.out/'state.db',session_id=self.out.name,workspace=str(self.work)),access=lambda *a:True,resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
            self.core=core;adapter=CodexCheckpointAdapter()
            core.ingest(adapter.import_items(prefix,thread_id=parent.opened['thread']['id'],start_ordinal=len(bootstrap)))
            first_selector=self.new('selector-1');first_receiver=self.new('receiver-1');snapshot=core.capture()
            offered=self.preflight(core,snapshot,None,1,first_selector)
            first=self.select(core,snapshot,None,1,first_selector,offered);self.publish(core,first,1,first_receiver,bootstrap)
            append_history(parent,delta,self.out/'raw-delta-import.json');append_history(first_receiver,delta,self.out/'wsc-delta-import.json')
            core.ingest(adapter.import_items(delta,thread_id=parent.opened['thread']['id'],start_ordinal=len(bootstrap)+len(prefix)))
            snapshot=core.capture();selector=self.new('selector-2');receiver=self.new('receiver-2')
            offered=self.preflight(core,snapshot,first['continuation'],2,selector)
            old=[e for e in offered['events'] if e['seq']<=first['continuation']['cut']]
            if any(e['spans'] or e['text_in_frontier'] for e in old):raise ValueError('old_text_unexpectedly_inline')
            if self.target['nonce'] in canonical(offered):raise ValueError('predeclared_target_already_hot_not_recovery_eligible')
            legacy=SnapshotSourceAccess(core.store,snapshot,access=core.access);cursor=0;pages=[]
            for _ in range(3):
                page=legacy.find(self.target['receipt_id'],cursor=cursor);pages.append(page)
                if page['matches'] or page['complete'] or page['errors']:break
                cursor=page['next_cursor']
            if any(p['matches'] for p in pages):raise ValueError('legacy_target_not_beyond_budget')
            save(self.out/'legacy-discovery-control.json',pages)
            discovery=SnapshotLiteralAccess(core.store,snapshot,access=core.access).find(self.target['receipt_id'])
            hit=next(m for m in discovery['matches'] if m['seq']==2*self.public['target_build_number'])
            if json.loads(hit['text'])!=self.target:raise ValueError('snapshot_discovery_control_changed')
            save(self.out/'snapshot-discovery-control.json',discovery)
            self.result.update(old_source_count=len(old),target_source_seq=2*self.public['target_build_number'],target_nonce_not_inline=True,raw_parent_unqueried=True,native_comparisons=0)
            save(self.out/'preflight.json',self.result)
            if not self.execute:self.result['status']='admission_passed';return self.result
            second=self.select(core,snapshot,first['continuation'],2,selector,offered);self.publish(core,second,2,receiver,bootstrap)
            answer=self.probe('wsc-probe',receiver,self.query,'wsc')
            self.result.update(status='completed',answer=answer,score=score_answer(answer,self.oracle),wsc_generations=2)
        except Exception as error:self.result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            self.result['cleanup']={name:session.close() for name,session in self.sessions.items()}
            if any(not x['empty_confirmed'] for x in self.result['cleanup'].values()):self.result.update(status='failed_preserved',cleanup_unknown=True)
            for name,session in self.sessions.items():
                if not session.opened:continue
                snap=capture_rollout(session.opened['thread']['path'],archive=self.out/('closed-'+name+'.jsonl'))
                expected={r['response_id']:r['usage'] for p in self.phases.values() if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
                actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
                if expected!=actual or not snap.metadata['parse_complete']:
                    self.accounting_unknown();self.result.update(status='failed_preserved',accounting_unknown=name)
            self.result['seconds']=time.monotonic()-begin;save(self.out/'result.json',self.result)
        return self.result


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    public,oracle,target=build();base=read(args.registration)['sessions']['B'];parent=read(args.parent_envelope)
    caps=dict(max_total_tokens=520000,max_responses=12,max_seconds=900)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget({'R01/wsc':caps},caps)
    save(args.out/'registration.json',dict(case='late-recovery-qualification/1',public_sha256=seal(public),query_sha256=seal(questions(oracle)),
        target_build=270,target_seq=540,old_prefix_sources=641,limits=caps,repetitions=1,formal_native_comparison=False,
        selected_policy='compact_wire/minimal_selector/budget_results_v1/snapshot_literal_v1',automatic_retries=0,
        private_oracle_not_in_selector=True,first_selection_is_model_generated=args.execute,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        source_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),Path(__file__).with_name('late_recovery_case.py'),ROOT/'src/wsc/snapshot_literal_access.py',ROOT/'experiments/native_source_tool_budget.py',ROOT/'experiments/native_incremental_generation.py']}))
    save(args.out/'dataset.public.json',public)
    ready=probe_service(base,args.out/'service-readiness') if args.execute else dict(passed=True,model_calls=0)
    result=dict(status='readiness_failed',readiness=ready);boot=None
    try:
        if ready['passed']:
            work=args.out/'bootstrap-workspace';work.mkdir();reg={**base,'workspace':str(work),'sandbox':'read-only'}
            for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
            boot=fresh(reg,args.out/'bootstrap-session')
            boot.server.call('thread/inject_items',dict(threadId=boot.opened['thread']['id'],items=[message('assistant',dict(record_type='bench.bootstrap/1',id='late-recovery-runtime'))]))
            cell=LateCell(base,args.out/'R01',public,2,ledger,1,args.execute,boot);cell.target=target;cell.oracle=oracle;cell.query=canonical(questions(oracle))
            result=cell.run()
    finally:
        if boot:save(args.out/'bootstrap-cleanup.json',boot.close())
        save(args.out/'oracle.private.json',oracle)
        result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin};save(args.out/'result.json',result)
        if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],error=result.get('error'),score=result.get('score'),tokens=result['ledger']['study']['tokens'])))


if __name__=='__main__':main()
