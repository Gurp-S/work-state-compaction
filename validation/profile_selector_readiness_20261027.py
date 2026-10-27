"""Zero-model proof that account admission need not start a disposable actor."""
from pathlib import Path
import argparse,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,state
from native_rollout_snapshot import capture_rollout
from native_blackbox_sessions import fresh
from native_selector_runtime import PROFILE
from native_source_tool import SOURCE_TOOL
from blackbox_minimal_recovery_group import probe_service
from wsc.contracts import encode


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','workspace','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False);base=read(args.registration)['sessions']['B']
    legacy=probe_service(base,args.out/'legacy-disposable-admission')
    result=dict(model_calls=0,legacy_disposable_seconds=legacy['seconds'],legacy_admission_passed=legacy['passed']);session=None
    if not legacy['passed']:
        save(args.out/'result.json',result);print(result);return
    reg={**base,'workspace':str(args.workspace)}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    begin=time.perf_counter()
    try:
        session=fresh(reg,args.out/'actual-selector',dynamic_tools=[SOURCE_TOOL],selector_runtime=PROFILE)
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[dict(type='message',role='assistant',content=[dict(type='output_text',text='{"record_type":"source_selection_runtime/1"}')])]))
        before=capture_rollout(session.opened['thread']['path'],archive=args.out/'before-check.jsonl')
        start=time.perf_counter();limits=session.server.call('account/rateLimits/read',{})['rateLimits'];seconds=time.perf_counter()-start
        after=capture_rollout(session.opened['thread']['path'],archive=args.out/'after-check.jsonl')
        assert encode(state(before.rows))==encode(state(after.rows))
        assert not any(row['type']=='token_usage_record' for row in after.rows)
        passed=all(limits.get(key,{}).get('usedPercent',100)<100 for key in ('primary','secondary'))
        result.update(actual_selector_seconds=time.perf_counter()-begin,admission_call_seconds=seconds,passed=passed,
            effective_model_items_byte_identical_before_after=True,processes_legacy=2,processes_reused=1,
            scope='One admission observation; removes one separate startup, not a statistical model latency result. Actual selector remains alive through admission.')
    finally:
        result['cleanup']=session.close() if session else None;save(args.out/'result.json',result)
    print(result)


if __name__=='__main__':main()
