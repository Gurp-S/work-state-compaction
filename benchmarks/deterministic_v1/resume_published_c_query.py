"""Finish an unqueried, already imported C receiver without selecting again."""
from pathlib import Path
from types import SimpleNamespace
import argparse,time
from blackbox_minimal_recovery_group import native_query,probe_service
from blackbox_group_runner import effective,cold_entries
from native_blackbox_sessions import verify_material
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from native_evidence import read,save,file_hash,digest
from native_application_budget import StudyBudget
from blackbox_budget import close as close_budget


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    begin=time.monotonic();source=args.source;old=read(source/'result.json')
    if old['error']!='ValueError:application_budget_unknown_or_arm_missing' or (source/'query').exists():raise ValueError('source_query_not_undispatched')
    if any(not x['empty_confirmed'] for x in old['cleanup'].values()):raise ValueError('source_cleanup_unknown')
    phase=read(source/'selection/phase-outcome.json')
    if not phase['completed'] or phase['failure'] or not phase['usage_complete']:raise ValueError('source_selection_incomplete')
    proof,_=verify_transcript(capture_rollout(source/'selection/rollout.jsonl'),phase)
    if proof!=read(source/'generation/request-binding.json'):raise ValueError('source_selection_binding_changed')
    package=read(source/'package.json');receiver=source/'receiver-session'
    opened=read(receiver/'thread-fork.json');reg=read(receiver/'registration.json')
    path=Path(opened['thread']['path']);checksum=file_hash(path)
    if checksum!=file_hash(source/'closed-receiver.jsonl'):raise ValueError('source_receiver_changed')
    parent=SimpleNamespace(opened=opened,registration=reg,fork_binding=read(receiver/'ancestry/binding.json'))
    bootstrap=effective(parent,(receiver/'opened.jsonl').read_bytes())
    imported=verify_material(effective(parent,path.read_bytes()),bootstrap,package['items'],workspace=reg['workspace'])
    for entry in cold_entries(package):
        if file_hash(entry['path'])!=entry['sha256']:raise ValueError('cold_resource_changed')
    args.out.mkdir(parents=True,exist_ok=False);caps=dict(max_total_tokens=120000,max_responses=4,max_seconds=120)
    outer=read(args.parent_envelope)
    study_caps=dict(caps,max_seconds=180)
    if any(study_caps[k]>outer['remaining_limits'][k] for k in study_caps):raise ValueError('parent_allocation_insufficient')
    ledger=StudyBudget({'R03/wsc':caps},study_caps)
    save(args.out/'registration.json',dict(source=str(source),selection_reused=True,no_new_selection=True,
        completed_selection_binding=proof,receiver_import=imported,receiver_sha256=checksum,limits=caps,
        source_sha256={name:file_hash(source/name) for name in ['result.json','package.json','selection/phase-outcome.json','generation/request-binding.json']},
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    ready=probe_service(reg,args.out/'service-readiness');result=dict(status='readiness_failed',readiness=ready)
    if ready['passed']:
        result=native_query('R03',dict(path=str(path),sha256=checksum,opened=opened,registration=reg),read(source/'oracle.private.json'),args,ledger,caps,label='C')
    result={**result,'ledger':ledger.snapshot(),'seconds':time.monotonic()-begin}
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(outer,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(result['status'],result.get('scores'),result['ledger']['study']['tokens'])


if __name__=='__main__':main()
