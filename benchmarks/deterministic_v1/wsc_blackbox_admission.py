"""Reuse the qualified native pair; add one actual incremental WSC boundary."""
import argparse
from pathlib import Path
from hashlib import sha256
import json
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,manifest,state,file_hash
from native_rollout_snapshot import parse_rollout,capture_rollout
from native_application_budget import StudyBudget
from native_application_session import NativeApplicationSession
from native_incremental_candidate import prepare,admit_rendered,POLICY
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from wsc import WSC,Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from blackbox import score_answer,strict_json
from blackbox_budget import close as close_budget
from native_blackbox_sessions import fresh,verify_paths,import_fresh
from dataset import canonical


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','capability','native-pair','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    base=read(args.registration)['sessions']['B'];parent=read(args.capability/'parent.json')
    paired=read(args.native_pair/'result.json');pair_reg=read(args.native_pair/'registration.json')
    if paired['status']!='completed' or not paired['compression_confirmed'] or not paired['ledger']['study']['uncertain'] is False:
        raise ValueError('native_pair_not_qualified')
    if any(v.get('empty_confirmed') is not True for v in paired['cleanup'].values()):raise ValueError('native_pair_cleanup_unknown')
    if pair_reg['config']!={k:base[k] for k in ('model','effort','executable_sha256')}:raise ValueError('native_configuration_changed')
    root_raw=Path(parent['thread']['path']).read_bytes();original=state(parse_rollout(root_raw).rows)
    public=original[-1:];bootstrap=original[:-1]
    if public[0].get('role')!='assistant' or strict_json(public[0]['content'][0]['text']).get('record_type')!='blackbox_capability_fixture':
        raise ValueError('unexpected_public_fixture')
    work=args.capability/'public-workspace'
    parent_budget=read(args.parent_envelope)
    caps=dict(max_total_tokens=250000,max_responses=12,max_seconds=240)
    if any(caps[k]>parent_budget['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    arm_caps=dict(selection=dict(max_total_tokens=150000,max_responses=8,max_seconds=120),
                  continuation=dict(max_total_tokens=100000,max_responses=4,max_seconds=120))
    ledger=StudyBudget(arm_caps,caps);sessions={};phases={};result=dict(status='started',scope='Incremental WSC boundary qualification; same two-fact native input reused.')
    reg={**base,'workspace':str(work),'initial_manifest':manifest(work),'sandbox':'read-only','native_cleanup_terminal_observation':True}
    reg.pop('browser_cache',None);reg.pop('native_c_auto_compaction',None)
    save(args.out/'registration.json',dict(limits=caps,arm_limits=arm_caps,policy=POLICY,
        public_items=public,public_items_sha256=sha256(canonical(public).encode()).hexdigest(),
        reused_native_pair=str(args.native_pair),reused_native_result_sha256=file_hash(args.native_pair/'result.json'),
        reused_compression_proof_sha256=file_hash(args.native_pair/'compression-proof.json'),
        query_sha256=pair_reg['query_sha256'],parent_envelope_sha256=file_hash(args.parent_envelope),
        source_parent_sha256=sha256(root_raw).hexdigest(),
        code_sha256={str(p):file_hash(p) for p in [*Path(__file__).resolve().parent.glob('*.py'),
            ROOT/'experiments/native_incremental_candidate.py',ROOT/'experiments/native_incremental_generation.py',ROOT/'experiments/native_indexed_checkpoint.py']},
        uncontrolled=dict(internal_temperature=None,provider_seed=None,internal_summarizer_model=None),
        old_unknowns_preserved=True,automatic_retries=0,production_algorithm_changed=False))
    core=WSC(Store(args.out/'state.db',session_id=args.out.name,workspace=str(work)),access=lambda *a:True)
    adapter=CodexCheckpointAdapter()
    core.ingest(adapter.import_items(public,thread_id=parent['thread']['id'],start_ordinal=len(bootstrap)))
    def execute(arm,name,request,schema):
        ticket,granted=ledger.reserve(arm,arm_caps[arm])
        def record(phase):phases[name]=phase;save(args.out/(name+'-settlement.json'),ledger.settle(ticket,phase))
        phase=sessions[arm].execute_stage(request,args.out/name,granted,record,output_schema=schema)
        if not phase.get('completed') or phase.get('failure') or not phase.get('usage_complete'):
            raise ValueError('wsc_capability_phase_failed:'+name)
        return phase,args.out/name/'rollout.jsonl'
    operation=None
    try:
        # Both receivers are opened and checked before any model request.
        for arm in ('selection','continuation'):
            if arm=='selection':
                sessions[arm]=NativeApplicationSession(reg,args.out/(arm+'-session'));sessions[arm].open()
            else:sessions[arm]=fresh(reg,args.out/(arm+'-session'))
        limits=sessions['selection'].server.call('account/rateLimits/read',{})['rateLimits']
        if any(limits.get(k,{}).get('usedPercent',100)>=100 for k in ('primary','secondary')):raise ValueError('quota_unavailable')
        def selected(offered):
            verify_paths(sessions['selection'],[dict(path=e['cold_source']['path'],sha256=e['cold_source']['sha256']) for e in offered['events']],args.out/'selection-cold-access.json')
            return generate(offered,lambda request,schema:execute('selection','selection-phase',canonical(request),schema),args.out/'generation',short_span_handles=True)
        prepared=prepare(core,core.capture(),None,args.out/'cold-public',selected,source_projection=MODE)
        operation=core.stage(prepared['view'],directory=args.out/'exports',archive_directory=args.out/'cold-objects',adapter=IndexedCheckpointAdapter())
        package=admit_rendered(core.package(operation));check_evidence(core,package)
        save(args.out/'package.json',package);save(args.out/'continuation.json',prepared['continuation'])
        receiver=sessions['continuation'];import_fresh(receiver,package['items'],bootstrap,args.out/'continuation-session')
        # Existing production worker transfer: audited native import, no fabricated core HostReceipt.
        entries=[]
        def collect(value):
            if isinstance(value,dict):
                for path_key,hash_key in (('file_path','sha256'),('readable_path','readable_sha256')):
                    if path_key in value and hash_key in value:entries.append(dict(path=value[path_key],sha256=value[hash_key]))
                for nested in value.values():collect(nested)
            elif isinstance(value,list):
                for nested in value:collect(nested)
        collect(package)
        entries.extend(dict(path=package[k],sha256=package[k+'_sha256']) for k in ('source_index','understanding_index'))
        verify_paths(receiver,entries,args.out/'receiver-cold-access.json')
        core.discard(operation);operation=None
        query=pair_reg['same_query']
        if sha256(query.encode()).hexdigest()!=pair_reg['query_sha256']:raise ValueError('query_changed')
        schema=dict(type='object',properties=dict(answers=dict(type='array',items=dict(type='object',properties=dict(
            question_id=dict(type='string'),value=dict(type=['string','integer'])),required=['question_id','value'],additionalProperties=False))),required=['answers'],additionalProperties=False)
        phase,_=execute('continuation','continuation-phase',query,schema)
        if len(phase['finals'])!=1:raise ValueError('answer_not_unique')
        oracle=read(args.native_pair/'oracle.private.json')
        save(args.out/'oracle.private.json',oracle)
        result.update(status='completed',score=score_answer(phase['finals'][0]['text'],oracle),
            native_scores=paired['scores'],raw_fixture_not_inherited=True,bootstrap_equal=True,
            true_incremental_policy_used=True,native_import_audited=True,atomic_core_installation_claimed=False,
            package_rendered_bytes=len(canonical(package['items']).encode()),
            persisted_bytes=sum(p.stat().st_size for folder in ('cold-public','cold-objects','exports') for p in (args.out/folder).rglob('*') if p.is_file()),
            semantic_superiority_claimed=False,whole_campaign_usage_complete=False)
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']={name:session.close() for name,session in sessions.items()}
        for arm,session in sessions.items():
            if not session.opened:continue
            snap=capture_rollout(session.opened['thread']['path'],archive=args.out/('closed-'+arm+'.jsonl'))
            expected={r['response_id']:r['usage'] for phase in phases.values() if phase['thread_id']==session.opened['thread']['id']
                for r in phase['receipts']['response_receipts']}
            actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
            if not snap.metadata['exists'] and not expected and result.get('status')!='completed' and ledger.arms[arm]['started'] is None:
                continue # Configured-only receiver, no phase reserved or inference requested.
            if expected!=actual or not snap.metadata['parse_complete']:
                ledger.mark_unknown(arm);result.update(status='failed_preserved',closure_accounting_mismatch=True)
        result['ledger']=ledger.snapshot();result['seconds']=time.monotonic()-begin
        save(args.out/'result.json',result)
        if not result['ledger']['inflight']:
            closure=close_budget(parent_budget,result['ledger'],result['seconds'])
            save(args.out/'next-admission-envelope.json',dict(**closure,parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],error=result.get('error'),score=result.get('score',{}).get('counts'),seconds=result['seconds'])))


if __name__=='__main__':main()
