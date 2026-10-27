"""One C2 input-representation qualification reusing immutable actual C1."""
from pathlib import Path
from types import SimpleNamespace
import argparse,sqlite3,time
from blackbox_minimal_recovery_group import probe_service
from qualify_source_tool import run_candidate,PROFILE,ROOT
from native_application_budget import StudyBudget
from native_evidence import read,save,file_hash
from blackbox_budget import close as close_budget


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','admission','registration','source-tool-admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--latency-trace',action='store_true')
    parser.add_argument('--metadata-columns-admission',type=Path)
    parser.add_argument('--bound-windows-io',action='store_true');parser.add_argument('--reuse-selector-readiness',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    gate=read(args.admission/'result.json');source=args.source/'R01'
    if not gate['passed'] or gate['model_calls']!=0 or gate['codec_sha256']!=file_hash(ROOT/'experiments/native_event_table.py'):raise ValueError('table_codec_admission_invalid')
    if gate['source_database_sha256']!=file_hash(source/'state.db'):raise ValueError('source_database_changed')
    if args.metadata_columns_admission:
        columns=read(args.metadata_columns_admission/'result.json')
        if not columns['passed'] or columns['model_calls']!=0 or columns['codec_sha256']!=file_hash(ROOT/'experiments/native_metadata_columns.py') or columns['source_database_sha256']!=file_hash(source/'state.db'):raise ValueError('metadata_columns_admission_invalid')
    if not read(args.source/'audit.json')['passed']:raise ValueError('source_not_audited')
    with sqlite3.connect(source/'state.db') as db:
        # Prior C2 material must not leak through the full M cold catalog.
        if db.execute('SELECT count(*) FROM understandings').fetchone()[0]!=0:raise ValueError('source_has_prior_model_records_requires_clean_fork')
    parent=read(args.parent_envelope);caps=dict(max_total_tokens=320000,max_responses=8,max_seconds=360)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget({'wsc':caps},caps)
    names=['state.db','result.json','C1-continuation.json','C1-selection/phase-outcome.json','parent-session/thread-fork.json','parent-session/ancestry/binding.json']
    cohort=dict(id='metadata_columns_C2_qualification/1' if args.metadata_columns_admission else 'cold_event_rows_C2_qualification/1',dataset_type='late-recovery/1',sources={'R01':dict(path=str(source.resolve()),sha256={name:file_hash(source/name) for name in names})},
        arm_limits={'wsc':caps},query_limits=dict(max_total_tokens=120000,max_responses=4,max_seconds=120),service_ready=False)
    if args.reuse_selector_readiness:cohort['service_check_on_selector']=True
    save(args.out/'qualification-registration.json',dict(cohort=cohort,first_selection_reused=True,source=str(args.source),
        old_second_selection_and_all_usage_preserved=True,no_prior_M_records=True,candidate_attempts=1,formal_three_pair=False,
        admission=str(args.admission),admission_sha256=file_hash(args.admission/'result.json'),
        metadata_columns_admission=str(args.metadata_columns_admission) if args.metadata_columns_admission else None,
        metadata_columns_codec_sha256=file_hash(ROOT/'experiments/native_metadata_columns.py') if args.metadata_columns_admission else None,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    timing=None
    if args.latency_trace:
        from native_latency import LatencyRecorder
        timing=LatencyRecorder(args.out/'timing.jsonl')
    try:
        if args.reuse_selector_readiness:
            ready=dict(passed=True,scope='Admission deferred to actual selector before any model dispatch.')
        else:
            ready=(timing.call('integration.service_check',probe_service,read(args.registration)['sessions']['B'],args.out/'service-readiness')
                if timing else probe_service(read(args.registration)['sessions']['B'],args.out/'service-readiness'))
        result=dict(status='readiness_failed',readiness=ready)
        if ready['passed']:
            cohort['service_ready']=True
            candidate=SimpleNamespace(source=source,registration=args.registration,admission=args.source_tool_admission,
                parent_envelope=args.parent_envelope,out=args.out/'candidate',selector_runtime=PROFILE,budget_tool_results=True,
                snapshot_literal_search=True,cold_event_table=True,bound_windows_io=args.bound_windows_io,metadata_columns=args.metadata_columns_admission is not None)
            result=run_candidate(candidate,ledger=ledger,cohort=cohort,timing=timing)
    finally:
        if timing:
            from native_latency import summarize
            timing.close();save(args.out/'timing-summary.json',summarize(args.out/'timing.jsonl'))
    result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin}
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(result['status'],result.get('scores'),result['ledger']['study']['tokens'])


if __name__=='__main__':main()
