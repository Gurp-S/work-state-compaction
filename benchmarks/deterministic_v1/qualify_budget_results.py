"""One registered R01 repair qualification, retaining failed group evidence."""
from pathlib import Path
from types import SimpleNamespace
import argparse,time
from blackbox_minimal_recovery_group import probe_service
from qualify_source_tool import run_candidate,PROFILE
from native_application_budget import StudyBudget
from native_evidence import read,save,file_hash
from blackbox_budget import close as close_budget


def main():
    parser=argparse.ArgumentParser()
    for name in ('failed-group','replay','registration','admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    replay=read(args.replay/'result.json')
    if not replay['passed'] or replay['old_reads']!=8 or replay['new_reads']!=8 or replay['model_calls']!=0:raise ValueError('repair_replay_not_admitted')
    original=read(args.failed_group/'registration.json');failed=args.failed_group/'R01/C'
    phase=read(failed/'selection/phase-outcome.json')
    if phase['failure']!='WSCError:source_tool_callback_budget_exhausted':raise ValueError('original_failure_changed')
    if file_hash(failed/'selection/events.jsonl')!=replay['evidence_sha256']['selection/events.jsonl']:raise ValueError('replay_not_bound_to_failure')
    parent=read(args.parent_envelope);caps=dict(max_total_tokens=320000,max_responses=8,max_seconds=360)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();arm='R01/wsc';ledger=StudyBudget({arm:caps},caps)
    gate=dict(id='bounded-source-tool-results-R01/1',sources=original['sources'],arm_limits={arm:caps},
        query_limits=dict(max_total_tokens=120000,max_responses=4,max_seconds=120),service_ready=False)
    save(args.out/'qualification-registration.json',dict(cohort=gate,failed_group=str(args.failed_group),
        failed_result_sha256=file_hash(args.failed_group/'result.json'),replay=str(args.replay),
        replay_sha256=file_hash(args.replay/'result.json'),new_algorithm=False,access_cap_unchanged=True,
        named_protocol_variant='budget_results_v1',candidate_attempts=1,not_formal_three_pair=True,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    ready=probe_service(read(args.registration)['sessions']['B'],args.out/'service-readiness')
    result=dict(status='readiness_failed',readiness=ready)
    if ready['passed']:
        gate['service_ready']=True
        candidate=SimpleNamespace(source=Path(original['sources']['R01']['path']),registration=args.registration,
            admission=args.admission,parent_envelope=args.parent_envelope,out=args.out/'candidate',selector_runtime=PROFILE,budget_tool_results=True)
        result=run_candidate(candidate,ledger=ledger,arm=arm,cohort=gate)
    result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin}
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(result['status'],result.get('scores'),result['ledger']['study']['tokens'])


if __name__=='__main__':main()
