"""One C-only continuation qualification using an already paid selection."""
from pathlib import Path
from types import SimpleNamespace
import argparse,time
from blackbox_group_runner import (ROOT,fork_registration,effective,import_receiver,cold_entries,guard_trunk,answer_schema)
from native_study_fork_session import NativeForkSession
from native_evidence import read,save,file_hash,manifest
from native_rollout_snapshot import capture_rollout
from native_application_budget import StudyBudget
from blackbox_resource_probe import verify_paths
from blackbox_recovery_case import build
from blackbox import questions,score_answer
from blackbox_budget import close as close_budget
from dataset import canonical
from wsc import WSC,Store
from wsc.resource_io import ResourceIO
from wsc.publication import check_evidence


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','prepared','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    prepared=read(args.prepared/'result.json');source=Path(prepared['original_source']);run=source.parent
    if prepared['new_model_calls']!=0 or not prepared['selected_old_source_rehydrated_exactly']:raise ValueError('prepared_draft_not_qualified')
    prior=read(run/'result.json')
    if prior['ledger']['inflight']:raise ValueError('source_still_inflight')
    if any(c.get('empty_confirmed') is not True for cell in prior['repetitions'].values() for c in cell['cleanup'].values()):raise ValueError('source_process_cleanup_unknown')
    base=read(args.registration)['sessions']['B'];work=source/'public-workspace';reg={**base,'workspace':str(work),'sandbox':'read-only','initial_manifest':manifest(work),'native_cleanup_terminal_observation':True}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    if file_hash(reg['executable'])!=reg['executable_sha256']:raise ValueError('registered_executable_changed')
    package=read(args.prepared/'package.json');parent_budget=read(args.parent_envelope)
    caps=dict(max_total_tokens=100000,max_responses=2,max_seconds=120)
    if any(caps[k]>parent_budget['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    public=read(run/'dataset.public.json');rebuilt,oracle,_=build(public['seed'],public['receipt_count'])
    if rebuilt!=public:raise ValueError('fixture_changed')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget({'continuation':caps},caps)
    save(args.out/'registration.json',dict(scope='One C-only administrative draft-reuse continuation, not a new B/C repetition.',
        prepared_result_sha256=file_hash(args.prepared/'result.json'),parent_envelope_sha256=file_hash(args.parent_envelope),limits=caps,
        original_failures_and_unknown_usage_preserved=True,selection_calls=0,automatic_retries=0))
    boot=SimpleNamespace(opened=read(run/'bootstrap-session/opened.json'),registration={})
    source_parent=SimpleNamespace(opened=read(source/'parent-session/thread-fork.json'),fork_binding=read(source/'parent-session/ancestry/binding.json'))
    parent_raw=Path(source_parent.opened['thread']['path']).read_bytes()
    if file_hash(source_parent.opened['thread']['path'])!=file_hash(source/'closed-parent.jsonl'):raise ValueError('source_parent_changed')
    bootstrap=effective(source_parent,parent_raw)[:-(len(public['prefix'])+len(public['delta']))]
    sessions={};phases=[];result=dict(status='started',scores=None,selection_regenerated=False)
    try:
        receiver=NativeForkSession(fork_registration(reg,boot),args.out/'receiver-session');sessions['receiver']=receiver;receiver.open()
        import_receiver(receiver,package['items'],bootstrap,args.out/'receiver-session')
        verify_paths(receiver,cold_entries(package),args.out/'cold-access.json')
        core=WSC(Store(args.prepared/'state.db',session_id=package['binding']['session_id'],workspace=package['binding']['workspace']),access=lambda *a:True,resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
        check_evidence(core,package);core.discard(prepared['operation'])
        checksum=file_hash(receiver.opened['thread']['path'])
        probe=NativeForkSession(fork_registration(reg,receiver),args.out/'probe-session');sessions['probe']=probe;probe.open()
        rate=probe.server.call('account/rateLimits/read',{})['rateLimits']
        if any(rate.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
        ticket,grant=ledger.reserve('continuation',caps)
        def record(phase):phases.append(phase);save(args.out/'settlement.json',ledger.settle(ticket,phase))
        phase=probe.execute_stage(canonical(questions(oracle)),args.out/'query',grant,record,output_schema=answer_schema())
        if not phase.get('completed') or not phase.get('usage_complete') or phase.get('failure') or len(phase.get('finals',[]))!=1:raise ValueError('continuation_phase_failed')
        guard_trunk(receiver,checksum)
        result.update(status='completed',scores=score_answer(phase['finals'][0]['text'],oracle),actual_native_import_verified=True,
            atomic_core_install_claimed=False,selection_regenerated=False,source_store_rehydration_verified=True)
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']={name:session.close() for name,session in sessions.items()}
        if any(not c.get('empty_confirmed') for c in result['cleanup'].values()):result.update(status='failed_preserved',cleanup_unknown=True)
        for name,session in sessions.items():
            if not session.opened:continue
            snap=capture_rollout(session.opened['thread']['path'],archive=args.out/('closed-'+name+'.jsonl'))
            expected={r['response_id']:r['usage'] for p in phases if p['thread_id']==session.opened['thread']['id'] for r in p['receipts']['response_receipts']}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            if expected!=actual or not snap.metadata['parse_complete']:
                ledger.mark_unknown('continuation');result.update(status='failed_preserved',closure_accounting_mismatch=name)
        result['ledger']=ledger.snapshot();result['seconds']=time.monotonic()-begin;save(args.out/'result.json',result)
        if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent_budget,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],error=result.get('error'),score=(result.get('scores') or {}).get('counts'),tokens=result['ledger']['study']['tokens'])))


if __name__=='__main__':main()
