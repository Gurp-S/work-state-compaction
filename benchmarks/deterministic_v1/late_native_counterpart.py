"""Missing native/uncompressed counterpart of the frozen late C qualification.

No summary inspection and no LLM judge. Reuse is explicitly historical.
"""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import argparse,json,time
from blackbox_group_runner import ROOT,effective,fork_registration,guard_trunk,answer_schema,compare_histories
from blackbox_recovery_runner import append_history
from late_recovery_case import build
from blackbox import questions,score_answer,compression_evidence
from dataset import canonical,seal
from native_evidence import read,save,file_hash,manifest
from native_study_fork_session import NativeForkSession
from native_rollout_snapshot import capture_rollout
from native_application_budget import StudyBudget
from native_latency import LatencyRecorder,attach,summarize
from blackbox_budget import close as close_budget


def run_arm(label,args,registration,oracle,ledger):
    out=args.out/label;out.mkdir(parents=True,exist_ok=False)
    base=read(args.source/'R01/parent-session/registration.json')
    boot=SimpleNamespace(opened=read(args.source/'bootstrap-session/opened.json'),registration={})
    reg=fork_registration(base,boot);reg['initial_manifest']=manifest(reg['workspace'])
    sessions={};phases=[];result=dict(status='started');begin=time.monotonic()
    with LatencyRecorder(out/'timing.jsonl') as timing:
        def opened(name,parent=None):
            child=fork_registration(reg,parent) if parent else reg
            session=NativeForkSession(child,out/(name+'-session'));sessions[name]=session
            timing.call('integration.start.'+name,session.open);attach(session,timing,name)
            return session
        def phase(session,name,request,*,compact=False):
            spec=dict(max_total_tokens=200000,max_responses=4,max_seconds=240) if compact else registration['query_limits']
            ticket,grant=ledger.reserve(label,spec)
            def record(value):phases.append(value);save(out/(name+'-settlement.json'),ledger.settle(ticket,value))
            value=session.execute_stage(request,out/name,grant,record,compact=compact,output_schema=None if compact else answer_schema())
            if not value.get('completed') or value.get('failure') or not value.get('usage_complete'):raise ValueError('phase_incomplete:'+name)
            return value
        try:
            session=opened('history')
            # Admission on the actual actor: no disposable readiness process.
            limits=session.server.call('account/rateLimits/read',{})['rateLimits']
            if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
            public=read(args.source/'dataset.public.json')
            append_history(session,public['prefix'],out/'prefix-import.json')
            source=SimpleNamespace(opened=read(args.source/'R01/parent-session/thread-fork.json'),fork_binding=read(args.source/'R01/parent-session/ancestry/binding.json'))
            original=effective(source,Path(source.opened['thread']['path']).read_bytes())
            expected=original[:-len(public['delta'])]
            proof=compare_histories([effective(session,Path(session.opened['thread']['path']).read_bytes()),expected],reg['workspace'])
            save(out/'same-prefix.json',proof)
            if not args.execute:
                result.update(status='admission_passed',model_calls=0);return result
            for number in (1,2):
                if number==2:append_history(session,public['delta'],out/'delta-import.json')
                if label=='B':
                    before=Path(session.opened['thread']['path']).read_bytes();name=f'B{number}-compression'
                    value=phase(session,name,'explicit idle compression',compact=True)
                    events=[json.loads(s) for s in (out/name/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                    proof=compression_evidence(before,(out/name/'rollout.jsonl').read_bytes(),value,events)
                    save(out/(name+'-proof.json'),proof)
                    if not proof['confirmed']:raise ValueError('native_compaction_unconfirmed')
            if label=='U':
                save(out/'same-full-history.json',compare_histories([effective(session,Path(session.opened['thread']['path']).read_bytes()),original],reg['workspace']))
            before=file_hash(session.opened['thread']['path']);probe=opened('probe',session)
            value=phase(probe,'query',canonical(questions(oracle)));guard_trunk(session,before)
            if len(value['finals'])!=1:raise ValueError('query_final_not_unique')
            result.update(status='completed',scores=score_answer(value['finals'][0]['text'],oracle))
        except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
        finally:
            result['cleanup']={name:timing.call('integration.close.'+name,s.close) for name,s in sessions.items()}
            if any(not x['empty_confirmed'] for x in result['cleanup'].values()):result.update(status='failed_preserved',cleanup_unknown=True)
            for name,s in sessions.items():
                if not s.opened:continue
                snap=capture_rollout(s.opened['thread']['path'],archive=out/('closed-'+name+'.jsonl'))
                expected={r['response_id']:r['usage'] for p in phases if p['thread_id']==s.opened['thread']['id'] for r in p['receipts']['response_receipts']}
                actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
                if expected!=actual or not snap.metadata['parse_complete']:
                    ledger.mark_unknown(label);result.update(status='failed_preserved',accounting_unknown=name)
            result['seconds']=time.monotonic()-begin;save(out/'result.json',result)
    save(out/'timing-summary.json',summarize(out/'timing.jsonl'))
    return result


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','reuse-c','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    public=read(args.source/'dataset.public.json');rebuilt,oracle,_=build(public['seed'],public['receipt_count'],public['target_build_number'])
    if public!=rebuilt:raise ValueError('public_changed')
    reused=read(args.reuse_c/'result.json')
    if reused['status']!='completed' or not read(args.reuse_c/'source-tool-audit.json')['passed']:raise ValueError('C_reuse_unqualified')
    if not read(args.reuse_c.parent/'table-run-audit.json')['passed']:raise ValueError('C_table_reuse_unqualified')
    reused_reg=read(args.reuse_c/'registration.json')
    if reused_reg['source']!=str((args.source/'R01').resolve()):raise ValueError('C_source_mismatch')
    base=read(args.source/'R01/parent-session/registration.json')
    if reused_reg['actor']!={k:base[k] for k in ('model','effort','executable_sha256')}:raise ValueError('actor_changed')
    if read(args.reuse_c/'query/attempt.json')['request']!=canonical(questions(oracle)):raise ValueError('query_changed')
    query=dict(max_total_tokens=120000,max_responses=4,max_seconds=120)
    arms={'B':dict(max_total_tokens=520000,max_responses=12,max_seconds=600),'U':query}
    caps=dict(max_total_tokens=640000,max_responses=16,max_seconds=660);parent=read(args.parent_envelope)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('campaign_allocation_insufficient')
    source_paths=[args.source/'R01/state.db',args.source/'R01/parent-session/thread-fork.json',args.reuse_c/'result.json',args.reuse_c/'registration.json']
    parent_path=Path(read(args.source/'R01/parent-session/thread-fork.json')['thread']['path']);source_paths.append(parent_path)
    frozen={str(p):file_hash(p) for p in source_paths}
    registration=dict(id='late-native-counterpart/1',case='late-recovery/1',repetition='R01',query_limits=query,arm_limits=arms,limits=caps,
        original_history_sha256=seal(public),query_sha256=seal(questions(oracle)),source_sha256=frozen,code_sha256=file_hash(Path(__file__)),
        reused_C=str(args.reuse_c),historical_C_outcome_known=True,reused_C_cost_not_new_spend=True,
        workers=2,automatic_retries=0,native_two_actual_compactions=True,summary_inspection=False,
        scope='One mixed historical/prospective system comparison; not three repetitions or algorithm-level causation. Native cold/warm internals unknown; no C latency performance claim.',
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope))
    args.out.mkdir(parents=True,exist_ok=False);save(args.out/'registration.json',registration)
    begin=time.monotonic();ledger=StudyBudget(arms,caps)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending={label:pool.submit(run_arm,label,args,registration,oracle,ledger) for label in ('B','U')}
        results={}
        for label,future in pending.items():
            try:results[label]=future.result()
            except Exception as error:results[label]=dict(status='failed_preserved',error=type(error).__name__+':'+str(error))
    unchanged=all(file_hash(Path(p))==h for p,h in frozen.items())
    result=dict(status='completed' if unchanged and all(v['status'] in ('completed','admission_passed') for v in results.values()) else 'failed_preserved',
        results=results,reused_C_scores=reused['scores'],source_unchanged=unchanged,ledger=ledger.snapshot(),seconds=time.monotonic()-begin,
        whole_campaign_usage_complete=False,prior_unknown_preserved=True)
    save(args.out/'oracle.private.json',oracle);save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(result))


if __name__=='__main__':main()
