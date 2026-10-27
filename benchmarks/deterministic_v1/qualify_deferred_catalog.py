"""One new C2 delivery policy qualification, reusing accepted C1 only."""
from pathlib import Path
from types import SimpleNamespace
import argparse,time
from qualify_source_tool import run_candidate,PROFILE,ROOT
from native_evidence import read,save,file_hash
from native_application_budget import StudyBudget
from native_latency import LatencyRecorder,summarize
from blackbox_budget import close


def main():
    p=argparse.ArgumentParser()
    for name in ('source','admission','source-tool-admission','parent-envelope','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--execute',action='store_true');args=p.parse_args()
    if not args.execute:p.error('Explicit --execute required')
    gate=read(args.admission/'result.json');source=args.source/'R01'
    if not gate['passed'] or gate['model_calls']!=0 or gate['source_database_sha256']!=file_hash(source/'state.db'):raise ValueError('deferred_catalog_admission_invalid')
    if any(file_hash(ROOT/'experiments'/name)!=sha for name,sha in gate['codecs_sha256'].items()):raise ValueError('admitted_code_changed')
    caps=dict(max_total_tokens=320000,max_responses=8,max_seconds=360);parent=read(args.parent_envelope)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('campaign_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget({'wsc':caps},caps)
    names=['state.db','result.json','C1-continuation.json','C1-selection/phase-outcome.json','parent-session/thread-fork.json','parent-session/ancestry/binding.json']
    cohort=dict(id='deferred_catalog_C2_qualification/1',dataset_type='late-recovery/1',sources={'R01':dict(path=str(source.resolve()),sha256={n:file_hash(source/n) for n in names})},
        arm_limits={'wsc':caps},query_limits=dict(max_total_tokens=120000,max_responses=4,max_seconds=120),service_check_on_selector=True)
    save(args.out/'qualification-registration.json',dict(cohort=cohort,source=str(args.source),C1_reused=True,C1_original_outcome_known=True,formal_BC=False,automatic_retries=0,
        resource_change='Catalog shares the same eight calls; up to one additional round trip, snapshot metadata scan/permission work separately disclosed.',
        admission=str(args.admission),admission_sha256=file_hash(args.admission/'result.json'),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        code_sha256={p.name:file_hash(p) for p in [Path(__file__),Path(__file__).with_name('qualify_source_tool.py')]}))
    save(args.out/'actor-registration.json',dict(sessions={'B':read(source/'parent-session/registration.json')}))
    candidate=SimpleNamespace(source=source,registration=args.out/'actor-registration.json',admission=args.source_tool_admission,parent_envelope=args.parent_envelope,out=args.out/'candidate',
        selector_runtime=PROFILE,budget_tool_results=True,snapshot_literal_search=True,cold_event_table=False,metadata_columns=False,deferred_catalog=True,bound_windows_io=True)
    try:
        with LatencyRecorder(args.out/'timing.jsonl') as timing:result=run_candidate(candidate,ledger=ledger,cohort=cohort,timing=timing)
    finally:save(args.out/'dispatch-ledger.json',ledger.snapshot())
    save(args.out/'timing-summary.json',summarize(args.out/'timing.jsonl'))
    result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin};save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(dict(status=result['status'],tokens=result['ledger']['study']['tokens'],responses=result['ledger']['study']['responses']))


if __name__=='__main__':main()
