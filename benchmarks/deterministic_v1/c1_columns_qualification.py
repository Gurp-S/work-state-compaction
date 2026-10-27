"""One new full C chain: compact first-stage metadata, stable C2 row policy."""
from pathlib import Path
import argparse,time
from late_recovery_qualification import LateCell
from late_recovery_case import build
from blackbox_group_runner import ROOT
from blackbox_recovery_case import message
from blackbox import questions
from dataset import canonical,seal
from native_evidence import read,save,file_hash
from native_blackbox_sessions import fresh
from native_application_budget import StudyBudget
from native_latency import LatencyRecorder,attach,summarize
from native_incremental_generation import generate
from native_incremental_candidate import prepare
from native_source_tool_budget import BudgetResultSourceToolHandler
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from wsc.bound_windows_io import BoundWindowsIO
from wsc.source_reference_view import MODE
from blackbox_budget import close as close_budget


class ColumnCell(LateCell):
    def new(self,name,parent=None):
        session=self.timing.call('integration.start.'+name,super().new,name,parent)
        return attach(session,self.timing,name)

    def select(self,core,snapshot,previous,number,selector,offered):
        core.resource_io=BoundWindowsIO()
        handler=BudgetResultSourceToolHandler(SnapshotLiteralAccess(core.store,snapshot,access=core.access))
        def selected(value):
            def execute(request,schema):
                phase=self.phase(f'selector-{number}','wsc',f'C{number}-selection',canonical(request),schema=schema,tool_handler=handler)
                return phase,self.out/f'C{number}-selection/rollout.jsonl'
            return generate(value,execute,self.out/f'C{number}-generation',short_span_handles=True,compact_wire=True,source_access=handler.describe(),
                event_columns=number==1,metadata_columns=number==1,cold_event_table=number==2)
        try:
            return self.timing.call('selection.pipeline.C'+str(number),prepare,core,snapshot,previous,self.out/'cold-public',selected,source_projection=MODE)
        finally:save(self.out/f'C{number}-tool-trace.json',handler.trace)


def settle_bootstrap(boot,ledger,timing,out):
    try:
        if boot:
            with timing.span('integration.bootstrap_close'):
                cleanup=boot.close()
            save(out/'bootstrap-cleanup.json',cleanup)
    finally:
        # Postprocessing/cleanup errors cannot discard the live ledger.
        save(out/'dispatch-ledger.json',ledger.snapshot())


def run(args,*,ledger=None,repetition=1):
    if not args.execute:raise ValueError('Explicit --execute required')
    gate=read(args.admission/'result.json')
    if not gate['passed'] or gate['model_calls']!=0 or gate['source_database_sha256']!=file_hash(args.source/'R01/state.db'):raise ValueError('admission_invalid')
    if any(file_hash(ROOT/'experiments'/name)!=sha for name,sha in gate['codecs_sha256'].items()):raise ValueError('admitted_codec_changed')
    parent=read(args.parent_envelope);caps=dict(max_total_tokens=520000,max_responses=12,max_seconds=900)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('campaign_allocation_insufficient')
    own_ledger=ledger is None;slot=f'R{repetition:02d}/wsc'
    if ledger is not None and (slot not in ledger.snapshot()['arms'] or ledger.snapshot()['arms'][slot]['limits']!=caps):raise ValueError('shared_arm_unregistered')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    if own_ledger:ledger=StudyBudget({slot:caps},caps)
    public,oracle,target=build();base=read(args.source/'R01/parent-session/registration.json')
    if public!=read(args.source/'dataset.public.json'):raise ValueError('source_public_changed')
    for k in ('parent_thread_id','parent_paths','before_turn_id','browser_cache','native_c_auto_compaction'):base.pop(k,None)
    save(args.out/'registration.json',dict(id='C1_event_columns_full_chain/1',C1_reused=False,C2_policy='stable cold_event_table without metadata_columns',
        source=str(args.source),public_sha256=seal(public),query_sha256=seal(questions(oracle)),limits=caps,repetitions=1,new_native_comparison=False,
        historical_outcomes_known=True,automatic_retries=0,cohort_arm=slot,shared_ledger=not own_ledger,parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),admission_sha256=file_hash(args.admission/'result.json'),
        code_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),ROOT/'experiments/native_event_columns.py',ROOT/'experiments/native_metadata_columns.py',ROOT/'experiments/native_incremental_generation.py']}))
    save(args.out/'dataset.public.json',public);boot=None;result=dict(status='readiness_failed')
    with LatencyRecorder(args.out/'timing.jsonl') as timing:
        try:
            work=args.out/'bootstrap-workspace';work.mkdir();reg={**base,'workspace':str(work),'sandbox':'read-only'}
            boot=timing.call('integration.bootstrap',fresh,reg,args.out/'bootstrap-session');attach(boot,timing,'bootstrap')
            limits=boot.server.call('account/rateLimits/read',{})['rateLimits']
            if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
            boot.server.call('thread/inject_items',dict(threadId=boot.opened['thread']['id'],items=[message('assistant',dict(record_type='bench.bootstrap/1',id='late-recovery-runtime'))]))
            cell=ColumnCell(base,args.out/'R01',public,2,ledger,repetition,True,boot);cell.timing=timing;cell.target=target;cell.oracle=oracle;cell.query=canonical(questions(oracle))
            result=cell.run()
        except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            settle_bootstrap(boot,ledger,timing,args.out)
    save(args.out/'timing-summary.json',summarize(args.out/'timing.jsonl'))
    save(args.out/'oracle.private.json',oracle);result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin};save(args.out/'result.json',result)
    if own_ledger and not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],arm=slot,error=result.get('error'),score=result.get('score'),tokens=result['ledger']['arms'][slot]['tokens'])),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');run(parser.parse_args())


if __name__=='__main__':main()
