"""Resume three frozen two-boundary pairs; reuse qualified R02, no new judge."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from types import SimpleNamespace
import argparse,json,time,sqlite3
from qualify_source_tool import run_candidate,PROFILE,CANDIDATE
from blackbox_group_runner import fork_registration,guard_trunk,answer_schema,ROOT
from native_study_fork_session import NativeForkSession
from native_evidence import read,save,file_hash,manifest
from native_rollout_snapshot import capture_rollout
from native_application_budget import StudyBudget
from native_blackbox_sessions import fresh
from blackbox_recovery_case import build
from blackbox import questions,score_answer
from blackbox_budget import close as close_budget
from dataset import canonical,seal

ID='minimal-source-recovery-three-pairs/1'


def probe_service(base,out):
    """One coordinator account check before any model worker can start."""
    out.mkdir(parents=True,exist_ok=False);work=out/'workspace';work.mkdir()
    reg={**base,'workspace':str(work),'sandbox':'read-only','initial_manifest':{}}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    session=None;result=dict(passed=False,model_calls=0);begin=time.monotonic()
    try:
        session=fresh(reg,out/'session')
        response=session.server.call('account/rateLimits/read',{});save(out/'rate-limits.json',response)
        limits=response['rateLimits']
        if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
        result['passed']=True
    except Exception as error:result['error']=type(error).__name__+':'+str(error)
    finally:
        result['cleanup']=session.close() if session else None
        if session and not result['cleanup']['empty_confirmed']:result.update(passed=False,cleanup_unknown=True)
        result['seconds']=time.monotonic()-begin;save(out/'result.json',result)
    return result


def prepare(args):
    public=read(args.source/'dataset.public.json');rebuilt,oracle,_=build(public['seed'],public['receipt_count'])
    if public!=rebuilt:raise ValueError('source_dataset_changed')
    candidate=read(args.reuse/'registration.json');reused=read(args.reuse/'result.json')
    expected=CANDIDATE+'/'+PROFILE
    if candidate['policy']!=expected or candidate['source']!=str((args.source/'R02').resolve()):raise ValueError('reuse_policy_or_source_changed')
    if reused['status']!='completed' or reused['ledger']['study']['uncertain']:raise ValueError('reuse_incomplete')
    if not read(args.reuse/'source-tool-audit.json')['passed']:raise ValueError('reuse_not_audited')
    # Only orchestration changes after R02 qualify. Selection/recovery/runtime
    # implementation must remain identical to the reused actual candidate.
    for name,checksum in candidate['source_sha256'].items():
        if Path(name).as_posix()=='benchmarks/deterministic_v1/qualify_source_tool.py':continue
        if file_hash(ROOT/name)!=checksum:raise ValueError('reuse_core_implementation_changed:'+name)
    gate=read(args.admission/'result.json')
    if not gate.get('passed') or gate['model_calls']!=0 or not gate['cleanup']['empty_confirmed']:raise ValueError('source_tool_admission_invalid')
    sources={};parents={};raw_scores={}
    for number in (1,2,3):
        name=f'R{number:02d}';source=args.source/name;old=read(source/'result.json')
        if any(not x['empty_confirmed'] for x in old['cleanup'].values()):raise ValueError('source_cleanup_unknown')
        for boundary in (1,2):
            if not read(source/f'B{boundary}-compression-proof.json')['confirmed']:raise ValueError('native_compaction_not_confirmed')
        opened=read(source/'native-session/thread-fork.json');reg=read(source/'native-session/registration.json')
        path=Path(opened['thread']['path']);snap=capture_rollout(path)
        if not snap.metadata['parse_complete'] or file_hash(path)!=file_hash(source/'closed-native.jsonl'):raise ValueError('native_parent_not_frozen')
        if (source/'native-probe').exists():raise ValueError('native_post_query_already_dispatched')
        proof=read(source/'B2-compression-proof.json')
        if proof['thread_id']!=opened['thread']['id']:raise ValueError('native_proof_parent_mismatch')
        phase=read(source/'uncompressed-probe/phase-outcome.json')
        if len(phase['finals'])!=1 or not phase['usage_complete']:raise ValueError('uncompressed_baseline_incomplete')
        raw_scores[name]=score_answer(phase['finals'][0]['text'],oracle)
        names=['state.db','C1-continuation.json','C1-selection/phase-outcome.json','result.json',
            'parent-session/thread-fork.json','parent-session/ancestry/binding.json','native-session/thread-fork.json',
            'native-session/registration.json','B1-compression-proof.json','B2-compression-proof.json','closed-native.jsonl']
        sources[name]=dict(path=str(source.resolve()),sha256={key:file_hash(source/key) for key in names},
            prior_error=old.get('error'),prior_failure_and_unknown_preserved=True)
        parents[name]=dict(path=str(path),sha256=file_hash(path),opened=opened,registration=reg)
    query_limits=dict(max_total_tokens=args.query_tokens,max_responses=args.query_responses,max_seconds=120)
    if query_limits not in (dict(max_total_tokens=60000,max_responses=2,max_seconds=120),dict(max_total_tokens=120000,max_responses=4,max_seconds=120)):raise ValueError('query_budget_unregistered')
    reused_native={}
    if getattr(args,'reuse_native',None):
        old=read(args.reuse_native/'result.json')
        if old['status']!='failed_preserved':raise ValueError('partial_native_group_not_failed')
        for name in sources:
            value=old['results'].get(name+'/B',{})
            if value.get('status')!='completed':continue
            path=args.reuse_native/name/'B';phase=read(path/'query/phase-outcome.json')
            if not phase['usage_complete'] or not value['cleanup']['empty_confirmed'] or phase['receipts']['response_count']>query_limits['max_responses'] or phase['receipts']['all_usage']['total_tokens']>query_limits['max_total_tokens']:raise ValueError('native_reuse_outside_new_budget')
            old_reg=read(args.reuse_native/'registration.json')
            if old_reg['sources'][name]!=sources[name] or old_reg['query_sha256']!=seal(questions(oracle)):raise ValueError('native_reuse_input_changed')
            reused_native[name]=dict(path=str(path.resolve()),result_sha256=file_hash(path/'result.json'),
                originally_completed_under_smaller_nonbinding_budget=True)
    arms={f'{name}/native':dict(query_limits) for name in sources if name not in reused_native}
    arms.update({f'{name}/wsc':dict(max_total_tokens=200000+query_limits['max_total_tokens'],max_responses=4+query_limits['max_responses'],max_seconds=360) for name in ('R01','R03')})
    caps=dict(max_total_tokens=sum(x['max_total_tokens'] for x in arms.values()),max_responses=sum(x['max_responses'] for x in arms.values()),max_seconds=600)
    parent=read(args.parent_envelope)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    registration=dict(id=ID,policy=expected,source=str(args.source.resolve()),sources=sources,native_parents=parents,
        public_sha256=seal(public),query_sha256=seal(questions(oracle)),oracle_not_in_selector=True,
        repetitions=3,workers=3,arm_limits=arms,limits=caps,query_limits=query_limits,reused_native=reused_native,strict_algorithm_comparison=False,
        reuse=dict(slot='R02',path=str(args.reuse.resolve()),outcome_known_at_registration=True,
            selection_sha256=file_hash(args.reuse/'selection/phase-outcome.json'),result_sha256=file_hash(args.reuse/'result.json')),
        prospective_slots=['R01','R03'],all_original_slots_retained=True,
        scope='System-level black-box comparison, mixed historical/prospective cohort; same one case, not three independent datasets.',
        prior_study_unknown_preserved=True,automatic_retries=0,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        code_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),ROOT/'benchmarks/deterministic_v1/qualify_source_tool.py']})
    if getattr(args,'prior_attempt',None):
        prior=read(args.prior_attempt/'result.json')
        partial=getattr(args,'reuse_native',None)
        if prior['status']!='failed_preserved' or (prior['ledger']['study']['responses']!=0 and (partial is None or partial.resolve()!=args.prior_attempt.resolve())):raise ValueError('prior_attempt_requires_explicit_partial_result_resume')
        registration['prior_infrastructure_attempt']=dict(path=str(args.prior_attempt.resolve()),result_sha256=file_hash(args.prior_attempt/'result.json'),
            known_tokens=prior['ledger']['study']['tokens'],usage_unknown=prior['ledger']['study']['uncertain'],retained=True)
    return registration,oracle,raw_scores


def native_query(name,parent,oracle,args,ledger,query_limits,*,label='B'):
    if label not in ('B','C'):raise ValueError('query_branch_label_invalid')
    out=args.out/name/label;out.mkdir(parents=True,exist_ok=False);session=None;phases=[];result=dict(status='started')
    reg=parent['registration'];source=SimpleNamespace(opened=parent['opened'],registration=reg)
    before=parent['sha256'];arm=name+('/native' if label=='B' else '/wsc')
    try:
        if file_hash(parent['path'])!=before:raise ValueError('native_source_changed_before_fork')
        child=fork_registration(reg,source);child['initial_manifest']=manifest(child['workspace'])
        session=NativeForkSession(child,out/'probe-session');session.open()
        ticket,grant=ledger.reserve(arm,query_limits)
        def record(phase):phases.append(phase);save(out/'query-settlement.json',ledger.settle(ticket,phase))
        phase=session.execute_stage(canonical(questions(oracle)),out/'query',grant,record,output_schema=answer_schema())
        if not phase.get('completed') or phase.get('failure') or not phase.get('usage_complete') or len(phase['finals'])!=1:raise ValueError('native_query_incomplete')
        guard_trunk(source,before)
        result.update(status='completed',scores=score_answer(phase['finals'][0]['text'],oracle))
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']=session.close() if session else None
        if session and session.opened:
            snap=capture_rollout(session.opened['thread']['path'],archive=out/'closed-probe.jsonl')
            expected={r['response_id']:r['usage'] for p in phases for r in p['receipts']['response_receipts']}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            if not snap.metadata['parse_complete'] or expected!=actual:
                ledger.mark_unknown(arm);result.update(status='failed_preserved',closure_accounting_unknown=True)
        if session and not result['cleanup']['empty_confirmed']:result.update(status='failed_preserved',cleanup_unknown=True)
        if file_hash(parent['path'])!=before:result.update(status='failed_preserved',source_changed=True)
        save(out/'result.json',result)
    return result


def run(args):
    begin=time.monotonic();registration,oracle,raw=prepare(args)
    args.out.mkdir(parents=True,exist_ok=False);save(args.out/'registration.json',registration)
    if not args.execute and not getattr(args,'check_service',False):
        result=dict(status='admission_passed',model_calls=0,seconds=time.monotonic()-begin,source_unchanged=True)
        save(args.out/'result.json',result);print(canonical(result));return result
    ledger=StudyBudget(registration['arm_limits'],registration['limits']);results={'R02/C':read(args.reuse/'result.json')}
    ready=probe_service(read(args.registration)['sessions']['B'],args.out/'service-readiness')
    registration['service_ready']=ready['passed']
    save(args.out/'service-admission.json',ready)
    if not ready['passed'] or not args.execute:
        result=dict(status='service_ready' if ready['passed'] else 'readiness_failed',model_calls=0,
            ledger=ledger.snapshot(),seconds=time.monotonic()-begin,readiness=ready,prior_unknown_preserved=True)
        save(args.out/'result.json',result)
        save(args.out/'next-admission-envelope.json',dict(**close_budget(read(args.parent_envelope),result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
        print(canonical(dict(status=result['status'],model_calls=0,error=ready.get('error'))));return result
    def collect(pending):
        for future in as_completed(pending):
            key=pending[future]
            try:results[key]=future.result()
            except Exception as error:results[key]=dict(status='failed_preserved',error=type(error).__name__+':'+str(error))
            print(canonical(dict(slot=key,status=results[key]['status'],error=results[key].get('error'))),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name,binding in registration['reused_native'].items():results[name+'/B']=read(Path(binding['path'])/'result.json')
        pending={}
        for name in ('R01','R03'):
            candidate=SimpleNamespace(source=args.source/name,registration=args.registration,admission=args.admission,
                parent_envelope=args.parent_envelope,out=args.out/name/'C',selector_runtime=PROFILE)
            pending[pool.submit(run_candidate,candidate,ledger=ledger,arm=name+'/wsc',cohort=registration)]=name+'/C'
        collect(pending)
        if all(results[name+'/C']['status']=='completed' for name in ('R01','R02','R03')) and not ledger.snapshot()['study']['uncertain']:
            collect({pool.submit(native_query,name,parent,oracle,args,ledger,registration['query_limits']):name+'/B' for name,parent in registration['native_parents'].items() if name not in registration['reused_native']})
    result=dict(status='completed' if len(results)==6 and all(x['status']=='completed' for x in results.values()) else 'failed_preserved',
        results=results,uncompressed_scores=raw,ledger=ledger.snapshot(),seconds=time.monotonic()-begin,
        reused_result_in_new_ledger=False,whole_campaign_usage_complete=False,prior_unknown_preserved=True)
    save(args.out/'oracle.private.json',oracle);save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(read(args.parent_envelope),result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],new_tokens=result['ledger']['study']['tokens'],new_responses=result['ledger']['study']['responses'])))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('source','reuse','registration','admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--check-service',action='store_true')
    parser.add_argument('--prior-attempt',type=Path);parser.add_argument('--reuse-native',type=Path)
    parser.add_argument('--query-responses',type=int,default=2);parser.add_argument('--query-tokens',type=int,default=60000)
    run(parser.parse_args())
