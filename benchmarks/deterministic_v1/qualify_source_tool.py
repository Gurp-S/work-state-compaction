"""C-only R02 continuation with a registered source-tool candidate policy.

Reuses C1 and the unchanged source stream. The original denied attempt and all
unknown accounting remain; this named interface variant gets one actual try.
"""
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
import argparse,sqlite3,json,time
from blackbox_group_runner import (ROOT,fork_registration,effective,import_receiver,cold_entries,guard_trunk,answer_schema)
from native_evidence import read,save,file_hash,manifest
from native_blackbox_sessions import fresh
from native_rollout_snapshot import capture_rollout
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_incremental_candidate import frontier,compile_draft,POLICY
from native_incremental_generation import generate
from native_incremental_compile import compile_choice
from native_source_tool import SOURCE_TOOL,SourceToolHandler
from native_indexed_checkpoint import IndexedCheckpointAdapter
from blackbox_resource_probe import verify_paths
from blackbox_recovery_case import build,decoded_objects
from blackbox import questions,score_answer
from blackbox_budget import close as close_budget
from dataset import canonical,seal
from wsc import WSC,Store,Limits
from wsc.source_access import SnapshotSourceAccess
from wsc.resource_io import ResourceIO
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from native_selector_runtime import PROFILE

CANDIDATE=POLICY['id']+'/source_tool_v1'


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','registration','admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--selector-runtime',choices=[PROFILE])
    parser.add_argument('--budget-tool-results',action='store_true')
    parser.add_argument('--snapshot-literal-search',action='store_true')
    parser.add_argument('--cold-event-table',action='store_true')
    parser.add_argument('--metadata-columns',action='store_true')
    parser.add_argument('--deferred-catalog',action='store_true')
    parser.add_argument('--bound-windows-io',action='store_true')
    parser.add_argument('--latency-trace',action='store_true')
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    if args.latency_trace:
        from native_latency import LatencyRecorder,summarize
        args.out.parent.mkdir(parents=True,exist_ok=True);path=args.out.with_name(args.out.name+'-timing.jsonl')
        with LatencyRecorder(path) as timing:run_candidate(args,timing=timing)
        save(args.out/'timing-summary.json',summarize(path))
    else:run_candidate(args)


def run_candidate(args,*,ledger=None,arm='wsc',cohort=None,timing=None):
    def measure(label,function,*values,**options):
        return timing.call(label,function,*values,**options) if timing else function(*values,**options)
    def instrument(session,component):
        if timing:
            from native_latency import attach
            attach(session,timing,component)
        return session
    own_ledger=ledger is None
    gate=read(args.admission/'result.json')
    if not gate.get('passed') or gate['model_calls']!=0 or not gate['cleanup']['empty_confirmed']:raise ValueError('source_tool_admission_not_passed')
    old=read(args.source/'result.json')
    if cohort is None:
        if (args.source/'C2-selection').exists() or not old.get('error','').endswith('application_budget_unknown_or_arm_missing'):raise ValueError('source_second_selection_not_unrequested_R02')
    else:
        if args.selector_runtime!=PROFILE or arm not in cohort['arm_limits']:raise ValueError('cohort_candidate_policy_mismatch')
        record=cohort['sources'].get(args.source.name)
        if record is None or str(args.source.resolve())!=record['path']:raise ValueError('cohort_source_not_registered')
        for name,checksum in record['sha256'].items():
            if file_hash(args.source/name)!=checksum:raise ValueError('cohort_source_changed:'+name)
    if any(not c['empty_confirmed'] for c in old['cleanup'].values()):raise ValueError('source_not_closed')
    source_run=args.source.parent;base=read(args.registration)['sessions']['B'];parent_budget=read(args.parent_envelope)
    caps=cohort['arm_limits'][arm] if cohort else dict(max_total_tokens=260000,max_responses=6,max_seconds=360)
    if any(caps[k]>parent_budget['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    public=read(source_run/'dataset.public.json')
    if cohort and cohort.get('dataset_type')=='late-recovery/1':
        from late_recovery_case import build as build_late
        rebuilt,oracle,_=build_late(public['seed'],public['receipt_count'],public['target_build_number'])
    else:rebuilt,oracle,_=build(public['seed'],public['receipt_count'])
    if public!=rebuilt:raise ValueError('public_stream_changed')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    if own_ledger:ledger=StudyBudget({'wsc':caps},caps)
    path=args.out/'state.db'
    with closing(sqlite3.connect(args.source/'state.db')) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    io_type=ResourceIO
    if getattr(args,'bound_windows_io',False):
        from wsc.bound_windows_io import BoundWindowsIO
        io_type=BoundWindowsIO
    core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,resource_io=io_type(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
    snapshot=measure('wsc.capture',core.capture);previous=read(args.source/'C1-continuation.json')
    material,offered=measure('wsc.frontier',frontier,core,snapshot,previous,args.out/'cold-public')
    handler_type=SourceToolHandler
    if getattr(args,'budget_tool_results',False):
        from native_source_tool_budget import BudgetResultSourceToolHandler
        handler_type=BudgetResultSourceToolHandler
    reader_type=SnapshotSourceAccess
    if getattr(args,'snapshot_literal_search',False):
        from wsc.snapshot_literal_access import SnapshotLiteralAccess
        reader_type=SnapshotLiteralAccess
    tool_spec=SOURCE_TOOL
    if getattr(args,'deferred_catalog',False):
        from native_catalog_tool import CatalogAccess,CatalogToolHandler,CATALOG_TOOL
        reader_type=CatalogAccess;handler_type=CatalogToolHandler;tool_spec=CATALOG_TOOL
    handler=handler_type(measure('wsc.reader_construction',reader_type,core.store,snapshot,access=core.access))
    reg={**base,'workspace':binding['workspace'],'sandbox':'read-only','initial_manifest':manifest(binding['workspace']),'native_cleanup_terminal_observation':True}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    policy=CANDIDATE if args.selector_runtime is None else CANDIDATE+'/'+args.selector_runtime
    if getattr(args,'budget_tool_results',False):policy+='/budget_results_v1'
    if getattr(args,'snapshot_literal_search',False):policy+='/snapshot_literal_v1'
    if getattr(args,'cold_event_table',False):policy+='/event_rows_v1'
    if getattr(args,'metadata_columns',False):policy+='/metadata_columns_v1'
    if getattr(args,'deferred_catalog',False):policy+='/deferred_catalog_v1'
    save(args.out/'registration.json',dict(policy=policy,selector_runtime=args.selector_runtime,case='source_tool_C_only_qualification',source=str(args.source),
        first_selection_reused=True,old_attempt_preserved=True,normal_second_selection_was_never_dispatched=not (args.source/'C2-selection').exists(),
        generation_attempts_for_this_named_candidate=1,stage_response_cap=4,limits=caps,
        cohort=(cohort['id'] if cohort else None),cohort_arm=arm,
        budget_errors_as_results=getattr(args,'budget_tool_results',False),
        snapshot_literal_search=getattr(args,'snapshot_literal_search',False),
        cold_event_table=getattr(args,'cold_event_table',False),
        metadata_columns=getattr(args,'metadata_columns',False),
        deferred_catalog=getattr(args,'deferred_catalog',False),
        bound_windows_io=getattr(args,'bound_windows_io',False),
        latency_trace=timing is not None,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        admission_result_sha256=file_hash(args.admission/'result.json'),original_source_result_sha256=file_hash(args.source/'result.json'),
        actor={k:reg[k] for k in ('model','effort','executable_sha256')},
        tool_added_only_to_C_selector=tool_spec,strict_algorithm_comparison=False,
        known_uncontrolled=['Internal summarizer parameters','Fresh selector bootstrap may differ from inherited native control; archived, not silently normalized.'],
        source_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [ROOT/'src/wsc/source_access.py',ROOT/'src/wsc/snapshot_literal_access.py',ROOT/'src/wsc/resource_io.py',ROOT/'src/wsc/bound_windows_io.py',ROOT/'experiments/native_source_tool.py',ROOT/'experiments/native_source_tool_budget.py',ROOT/'experiments/native_selection_wire.py',ROOT/'experiments/native_event_table.py',ROOT/'experiments/native_incremental_generation.py',ROOT/'experiments/native_application_session.py',ROOT/'experiments/native_selector_runtime.py',ROOT/'benchmarks/deterministic_v1/native_blackbox_sessions.py',Path(__file__)]}))
    sessions={};phases=[];result={'status':'started','scores':None}
    def execute(session_name,name,request,schema,*,tool_handler=None):
        phase_limits=dict(max_total_tokens=200000,max_responses=4,max_seconds=240) if tool_handler else (cohort['query_limits'] if cohort else dict(max_total_tokens=60000,max_responses=2,max_seconds=120))
        ticket,grant=ledger.reserve(arm,phase_limits)
        def record(value):phases.append(value);save(args.out/(name+'-settlement.json'),ledger.settle(ticket,value))
        phase=sessions[session_name].execute_stage(request,args.out/name,grant,record,output_schema=schema,tool_handler=tool_handler)
        if not phase.get('completed') or phase.get('failure') or not phase.get('usage_complete'):raise ValueError('candidate_phase_failed:'+name)
        return phase
    attempt=policy+':'+snapshot.source_digest
    try:
        selector=instrument(measure('integration.selector_start',fresh,reg,args.out/'selector-session',dynamic_tools=[tool_spec],selector_runtime=args.selector_runtime),'selector');sessions['selector']=selector
        selector.server.call('thread/inject_items',dict(threadId=selector.opened['thread']['id'],items=[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"record_type":"source_selection_runtime/1"}'}]}]))
        capture_rollout(selector.opened['thread']['path'],archive=args.out/'selector-bootstrap.jsonl')
        if cohort is None or cohort.get('service_check_on_selector'):
            limits=selector.server.call('account/rateLimits/read',{})['rateLimits']
            if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
            save(args.out/'selector-service-admission.json',dict(passed=True,model_calls=0,used_actual_selector=True))
        elif cohort.get('service_ready') is not True:raise ValueError('cohort_service_readiness_missing')
        core.begin_usage(attempt,phase='source_tool_candidate_selection')
        try:
            def generated(request,schema):
                loc=request['material']['cold_source_manifest'];measure('qualification.selector_manifest_check',verify_paths,selector,[dict(path=loc['path'],sha256=loc['sha256'])],args.out/'selection-manifest-access.json')
                phase=execute('selector','selection',canonical(request),schema,tool_handler=handler)
                return phase,args.out/'selection/rollout.jsonl'
            draft=measure('selection.pipeline',generate,offered,generated,args.out/'generation',short_span_handles=True,compact_wire=True,source_access=handler.describe(),cold_event_table=getattr(args,'cold_event_table',False),metadata_columns=getattr(args,'metadata_columns',False),deferred_catalog=handler if getattr(args,'deferred_catalog',False) else None)
            core.finish_usage(attempt,draft.usage)
        except Exception as error:
            from wsc.contracts import Usage
            core.finish_usage(attempt,getattr(error,'usage',Usage()),status='failed');raise
        selection=measure('wsc.compile_choice',compile_choice,material,previous,draft.selection,compile_draft)
        view=measure('wsc.prepare',core.prepare,snapshot,selection,producer=policy,limits=Limits(max_material_bytes=POLICY['max_material_bytes'],max_view_bytes=POLICY['max_view_body_bytes']),source_projection=MODE)
        op=measure('wsc.publication',core.stage,view,directory=args.out/'exports',archive_directory=args.out/'cold-objects',adapter=IndexedCheckpointAdapter())
        package=measure('wsc.package',core.package,op);measure('wsc.evidence_validation',check_evidence,core,package);save(args.out/'package.json',package)
        if len(canonical(package['items']).encode())>POLICY['max_rendered_bytes']:raise ValueError('candidate_render_budget_exhausted')
        boot=SimpleNamespace(opened=read(source_run/'bootstrap-session/opened.json'),registration={})
        source_parent=SimpleNamespace(opened=read(args.source/'parent-session/thread-fork.json'),fork_binding=read(args.source/'parent-session/ancestry/binding.json'))
        bootstrap=effective(source_parent,Path(source_parent.opened['thread']['path']).read_bytes())[:-(len(public['prefix'])+len(public['delta']))]
        receiver=NativeForkSession(fork_registration(reg,boot),args.out/'receiver-session');sessions['receiver']=receiver;measure('integration.receiver_start',receiver.open);instrument(receiver,'receiver')
        measure('integration.receiver_import',import_receiver,receiver,package['items'],bootstrap,args.out/'receiver-session');measure('qualification.receiver_cold_check',verify_paths,receiver,cold_entries(package),args.out/'receiver-access.json');measure('wsc.discard',core.discard,op)
        checksum=file_hash(receiver.opened['thread']['path'])
        probe=NativeForkSession(fork_registration(reg,receiver),args.out/'probe-session');sessions['probe']=probe;measure('qualification.probe_start',probe.open);instrument(probe,'probe')
        phase=execute('probe','query',canonical(questions(oracle)),answer_schema())
        guard_trunk(receiver,checksum)
        if len(phase.get('finals',[]))!=1:raise ValueError('query_answer_not_unique')
        result.update(status='completed',scores=score_answer(phase['finals'][0]['text'],oracle),source_tool_calls=len(handler.trace),
            selector_raw_history_inherited=False,strict_algorithm_comparison=False)
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        save(args.out/'source-tool-trace.json',handler.trace)
        result['source_tool_refused_callbacks']=getattr(handler,'refused_callbacks',0)
        result['cleanup']={name:measure('integration.close.'+name,session.close) for name,session in sessions.items()}
        if any(not c['empty_confirmed'] for c in result['cleanup'].values()):result.update(status='failed_preserved',cleanup_unknown=True)
        for name,session in sessions.items():
            if not session.opened:continue
            snap=capture_rollout(session.opened['thread']['path'],archive=args.out/('closed-'+name+'.jsonl'))
            expected={r['response_id']:r['usage'] for p in phases if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            if expected!=actual or not snap.metadata['parse_complete']:
                ledger.mark_unknown(arm);result.update(status='failed_preserved',closure_accounting_mismatch=name)
        result['ledger']=ledger.snapshot();result['seconds']=time.monotonic()-begin
        save(args.out/'oracle.private.json',oracle);save(args.out/'result.json',result)
        if own_ledger and not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent_budget,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],error=result.get('error'),score=(result.get('scores') or {}).get('counts'),tool_calls=len(handler.trace),tokens=result['ledger']['study']['tokens'])))
    return result


if __name__=='__main__':main()
