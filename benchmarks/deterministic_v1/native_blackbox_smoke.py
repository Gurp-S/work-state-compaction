"""One bounded, explicitly enabled native black-box capability experiment."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import manifest,save,read,file_hash
from native_study_fork_session import NativeForkSession
from native_recursive_fork import observe
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope
from blackbox import questions,score_answer,compression_evidence
from dataset import canonical
from blackbox_budget import close as close_budget


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--registration',type=Path,required=True)
    parser.add_argument('--capability',type=Path,required=True)
    parser.add_argument('--parent-envelope',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required for normal model calls')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    spec=read(args.registration);base=spec['sessions']['B'];cap=read(args.capability/'result.json')
    if not cap['passed'] or not cap['cleanup']['empty_confirmed']:raise ValueError('zero_call_capability_not_qualified')
    parent=read(args.capability/'parent.json');parent_envelope=read(args.parent_envelope)
    work=args.capability/'public-workspace'
    caps=dict(max_total_tokens=300000,max_responses=10,max_seconds=360)
    if any(caps[k]>parent_envelope['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    arm_caps={'baseline':dict(max_total_tokens=100000,max_responses=4,max_seconds=120),
              'compressed':dict(max_total_tokens=200000,max_responses=6,max_seconds=240)}
    ledger=StudyBudget(arm_caps,caps);sessions={};phases={};result=dict(status='started',scope='Native black-box capability only; not WSC comparison',scores={})
    oracle=dict(questions=[dict(question_id='value',question='What is the value in the blackbox_capability_fixture observation?',answer_type='integer',expected=41),
        dict(question_id='id',question='What is fixture_id in that observation?',answer_type='string',expected='same-history-1')])
    query=canonical(questions(oracle))
    schema=dict(type='object',properties=dict(answers=dict(type='array',items=dict(type='object',properties=dict(
        question_id=dict(type='string'),value=dict(type=['string','integer'])),required=['question_id','value'],additionalProperties=False))),required=['answers'],additionalProperties=False)
    save(args.out/'registration.json',dict(kind='bounded_native_blackbox_capability',limits=caps,arm_limits=arm_caps,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        old_unknowns_preserved=True,old_evaluation_remains_retired=True,automatic_retries=0,
        same_query=query,query_sha256=sha256(query.encode()).hexdigest(),oracle_not_in_model_input=True,
        config=dict(model=base['model'],effort=base['effort'],executable_sha256=base['executable_sha256']),
        scope='Two fact questions; one real native compression. No semantic performance claim.'))
    def execute(arm,name,*,compact=False):
        session=sessions[arm]
        limits=dict(max_total_tokens=100000,max_responses=2 if compact else 4,max_seconds=120)
        ticket,granted=ledger.reserve(arm,limits)
        def record(phase):
            phases[name]=phase;save(args.out/(name+'-settlement.json'),ledger.settle(ticket,phase))
        value=session.execute_stage('explicit idle compression' if compact else query,args.out/name,granted,record,
            compact=compact,output_schema=None if compact else schema)
        if not value.get('completed') or not value.get('usage_complete') or value.get('failure'):
            raise ValueError('capability_phase_failed:'+name)
        return value
    try:
        hashes=[]
        for arm in ('baseline','compressed'):
            reg={**base,'workspace':str(work),'initial_manifest':manifest(work),'sandbox':'read-only',
                'parent_thread_id':parent['thread']['id'],'parent_paths':{parent['thread']['id']:parent['thread']['path']},
                'native_cleanup_terminal_observation':True}
            reg.pop('browser_cache',None);reg.pop('native_c_auto_compaction',None)
            session=NativeForkSession(reg,args.out/(arm+'-session'));sessions[arm]=session;session.open()
            data=Path(session.opened['thread']['path']).read_bytes()
            hashes.append(observe(data,session.fork_binding)['evidence']['effective_items_sha256'])
        if len(set(hashes))!=1:raise ValueError('pre_probe_histories_differ')
        limits=sessions['baseline'].server.call('account/rateLimits/read',{})['rateLimits']
        if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
        baseline=execute('baseline','baseline-query')
        before=Path(sessions['compressed'].opened['thread']['path']).read_bytes()
        compact=execute('compressed','native-compression',compact=True)
        after=(args.out/'native-compression/rollout.jsonl').read_bytes()
        events=[json.loads(s) for s in (args.out/'native-compression/events.jsonl').read_text(encoding='utf-8').splitlines()]
        proof=compression_evidence(before,after,compact,events);save(args.out/'compression-proof.json',proof)
        if not proof['confirmed']:raise ValueError('compaction_not_confirmed')
        post=execute('compressed','compressed-query')
        # Gold and scores are only persisted after both sibling queries finish.
        save(args.out/'oracle.private.json',oracle)
        for name,phase in (('baseline',baseline),('compressed',post)):
            if len(phase['finals'])!=1:raise ValueError('final_answer_not_unique')
            result['scores'][name]=score_answer(phase['finals'][0]['text'],oracle)
        result.update(status='completed',same_pre_probe_history_sha256=hashes[0],compression_confirmed=True,
            model_effect_not_eliminated=True,summary_content_inspected=False,not_WSC_comparison=True)
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']={name:session.close() for name,session in sessions.items()}
        result['ledger']=ledger.snapshot();result['seconds']=time.monotonic()-begin
        result['whole_campaign_usage_complete']=False
        save(args.out/'result.json',result)
        if not result['ledger']['inflight']:
            envelope=close_budget(parent_envelope,result['ledger'],result['seconds'])
            save(args.out/'next-admission-envelope.json',dict(**envelope,
                parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
                zero_model_admission_time_not_in_phase_ledger=True))
    print(canonical(dict(status=result['status'],error=result.get('error'),scores={k:v['counts'] for k,v in result['scores'].items()},seconds=result['seconds'])))


if __name__=='__main__':main()
