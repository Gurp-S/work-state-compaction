"""Continue an already-generated, never-probed WSC package; no regeneration."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,manifest,state
from native_rollout_snapshot import capture_rollout,parse_rollout
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_recursive_fork import observe
from wsc import WSC,Store
from wsc.publication import check_evidence
from blackbox import score_answer
from blackbox_budget import close as close_budget
from native_blackbox_sessions import verify_material,verify_paths
from dataset import canonical


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','prepared','capability','native-pair','parent-envelope','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    original=read(args.prepared/'result.json');package=read(args.prepared/'package.json')
    if original['status']=='completed' or original['ledger']['study']['uncertain']:
        raise ValueError('prepared_run_not_safely_resumable')
    if any(v.get('empty_confirmed') is not True for v in original['cleanup'].values()):raise ValueError('previous_cleanup_unknown')
    source=read(args.prepared/'continuation-session/opened.json')
    parent_path=Path(source['thread']['path']);parent_raw=parent_path.read_bytes()
    if file_hash(parent_path)!=file_hash(args.prepared/'closed-continuation.jsonl'):
        raise ValueError('prepared_native_parent_changed')
    source_rows=parse_rollout(parent_raw).rows
    if any(r['type']=='token_usage_record' or r['type']=='event_msg' and r['payload'].get('type')=='task_started' for r in source_rows):
        raise ValueError('prepared_parent_already_probed')
    root=read(args.capability/'parent.json');bootstrap=state(parse_rollout(Path(root['thread']['path']).read_bytes()).rows)[:-1]
    base=read(args.registration)['sessions']['B'];work=args.capability/'public-workspace'
    proof=verify_material(state(source_rows),bootstrap,package['items'],workspace=str(work));save(args.out/'prepared-import-proof.json',proof)
    core=WSC(Store(args.prepared/'state.db',session_id=args.prepared.name,workspace=str(work)),access=lambda *a:True)
    check_evidence(core,package)
    parent_budget=read(args.parent_envelope);caps=dict(max_total_tokens=100000,max_responses=4,max_seconds=120)
    if any(caps[k]>parent_budget['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    ledger=StudyBudget(dict(continuation=caps),caps);session=None;phases=[]
    result=dict(status='started',regenerated_selection=False)
    save(args.out/'registration.json',dict(parent_envelope_sha256=file_hash(args.parent_envelope),limits=caps,
        prepared_result_sha256=file_hash(args.prepared/'result.json'),package_sha256=file_hash(args.prepared/'package.json'),
        native_parent_sha256=file_hash(parent_path),reused_selection_usage=original['ledger']['study'],automatic_retries=0,
        query_sha256=read(args.native_pair/'registration.json')['query_sha256'],old_unknowns_preserved=True))
    try:
        reg={**base,'workspace':str(work),'initial_manifest':manifest(work),'sandbox':'read-only',
            'parent_thread_id':source['thread']['id'],'parent_paths':{source['thread']['id']:str(parent_path)},
            'native_cleanup_terminal_observation':True}
        reg.pop('browser_cache',None);reg.pop('native_c_auto_compaction',None)
        session=NativeForkSession(reg,args.out/'receiver');session.open()
        actual=observe(Path(session.opened['thread']['path']).read_bytes(),session.fork_binding)['items']
        verify_material(actual,bootstrap,package['items'],workspace=str(work))
        entries=[]
        def collect(value):
            if isinstance(value,dict):
                for key,hashkey in (('file_path','sha256'),('readable_path','readable_sha256')):
                    if key in value and hashkey in value:entries.append(dict(path=value[key],sha256=value[hashkey]))
                for nested in value.values():collect(nested)
            elif isinstance(value,list):
                for nested in value:collect(nested)
        collect(package);entries.extend(dict(path=package[k],sha256=package[k+'_sha256']) for k in ('source_index','understanding_index'))
        verify_paths(session,entries,args.out/'cold-access.json')
        core.discard(package['operation_id']) # Audited import, not a synthetic installation receipt.
        pair_reg=read(args.native_pair/'registration.json');query=pair_reg['same_query']
        if sha256(query.encode()).hexdigest()!=pair_reg['query_sha256']:raise ValueError('query_changed')
        schema=dict(type='object',properties=dict(answers=dict(type='array',items=dict(type='object',properties=dict(
            question_id=dict(type='string'),value=dict(type=['string','integer'])),required=['question_id','value'],additionalProperties=False))),required=['answers'],additionalProperties=False)
        ticket,limits=ledger.reserve('continuation',caps)
        def record(phase):phases.append(phase);save(args.out/'settlement.json',ledger.settle(ticket,phase))
        phase=session.execute_stage(query,args.out/'query-phase',limits,record,output_schema=schema)
        if not phase['completed'] or not phase['usage_complete'] or phase['failure'] or len(phase['finals'])!=1:
            raise ValueError('wsc_continuation_incomplete')
        oracle=read(args.native_pair/'oracle.private.json');save(args.out/'oracle.private.json',oracle)
        result.update(status='completed',score=score_answer(phase['finals'][0]['text'],oracle),
            native_scores=read(args.native_pair/'result.json')['scores'],
            actual_incremental_selection=True,bootstrap_equal=True,raw_fixture_not_inherited=True,
            atomic_core_installation_claimed=False,selection_known_tokens=original['ledger']['study']['tokens'],
            semantic_superiority_claimed=False,whole_campaign_usage_complete=False)
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']=session.close() if session else dict(empty_confirmed=True,process_started=False)
        if session and session.opened:
            snap=capture_rollout(session.opened['thread']['path'],archive=args.out/'closed-native.jsonl')
            expected={r['response_id']:r['usage'] for phase in phases for r in phase['receipts']['response_receipts']}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            if actual!=expected or not snap.metadata['parse_complete']:ledger.mark_unknown('continuation');result['accounting_mismatch']=True
        result['ledger']=ledger.snapshot();result['seconds']=time.monotonic()-begin
        save(args.out/'result.json',result)
        if not result['ledger']['inflight']:
            closure=close_budget(parent_budget,result['ledger'],result['seconds'])
            save(args.out/'next-admission-envelope.json',dict(**closure,parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],error=result.get('error'),score=result.get('score',{}).get('counts'),seconds=result['seconds'])))


if __name__=='__main__':main()
