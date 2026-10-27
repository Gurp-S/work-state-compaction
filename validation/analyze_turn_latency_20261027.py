"""Server-clock decomposition; never equate buffered reasoning items to compute."""
from pathlib import Path
import argparse,json


def union_ms(intervals):
    result=0;end=None
    for a,b in sorted(intervals):
        if b<a:raise ValueError('timestamp_order_invalid')
        result+=b-max(a,end) if end is not None and a<end<b else (b-a if end is None or a>=end else 0)
        end=max(end,b) if end is not None else b
    return result


def analyze(root):
    phase=json.loads((root/'phase-outcome.json').read_text());tid=phase['usage_completion_evidence']['turn_id']
    events=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
    relevant=[e for e in events if e.get('params',{}).get('threadId')==phase['thread_id']]
    starts=[e for e in relevant if e.get('method')=='turn/started' and e['params']['turn']['id']==tid]
    ends=[e for e in relevant if e.get('method')=='turn/completed' and e['params']['turn']['id']==tid]
    if len(starts)!=1 or len(ends)!=1:raise ValueError('turn_timestamps_ambiguous')
    start=starts[0]['emittedAtMs'];end=ends[0]['emittedAtMs'];turn=(end-start)/1000
    items={};intervals=[];reason_items=0;deltas=0
    for e in relevant:
        t=e.get('emittedAtMs');p=e['params'];item=p.get('item',{});method=e.get('method')
        if type(t) is not int or not start<=t<=end:continue
        if method=='item/started' and item.get('type')=='dynamicToolCall':items[item['id']]=t
        if method=='item/completed' and item.get('type')=='dynamicToolCall':
            if item['id'] not in items:raise ValueError('tool_start_missing')
            intervals.append((items.pop(item['id']),t))
        if method=='item/started' and item.get('type')=='reasoning':reason_items+=1
        if method=='item/agentMessage/delta':deltas+=1
    if items:raise ValueError('tool_completion_missing')
    tool=union_ms(intervals)/1000;usage=phase['receipts']['all_usage']
    outside=phase['seconds']-turn
    if outside<-.1:raise ValueError('clock_domains_or_coverage_inconsistent')
    return dict(root=str(root),completed=phase['completed'],usage_complete=phase['usage_complete'],
        phase_seconds=phase['seconds'],server_turn_seconds=turn,reported_duration_seconds=ends[0]['params']['turn'].get('durationMs',0)/1000,
        dynamic_tool_count=len(intervals),dynamic_tool_union_seconds=tool,dynamic_tool_sum_seconds=sum(b-a for a,b in intervals)/1000,
        server_non_tool_seconds=turn-tool,phase_outside_server_turn_seconds=outside,
        output_tokens=usage['output_tokens'],reasoning_output_tokens=usage['reasoning_output_tokens'],
        aggregate_output_tokens_per_non_tool_second=usage['output_tokens']/(turn-tool) if turn>tool else None,
        reasoning_item_count=reason_items,agent_delta_count=deltas,retry_notices=len(phase['retry_notices']),
        failure=phase.get('failure'),noise_flags=['incomplete_or_failed'] if not phase['completed'] or not phase['usage_complete'] or phase.get('failure') else [],
        interpretation='Non-tool server interval includes inference, agent runtime, queue, prefill, network and batching. It is not pure model compute. Reasoning item start/end are delivery events, not thinking durations.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    runs=Path('D:/agent-task-runs');old=runs/'wsc-late-recovery-qualification-20261027-v1';new=runs/'wsc-event-table-qualification-20261027-v1'
    roots={'old_selection':old/'R01/C2-selection','old_query':old/'R01/wsc-probe','new_selection':new/'candidate/selection','new_query':new/'candidate/query'}
    rows={name:analyze(root) for name,root in roots.items()}
    totals={}
    for name,root,phase_names in [('old_full',old,['C1-selection','C2-selection','wsc-probe']),('new_followup',new,['selection','query'])]:
        result=json.loads((root/'result.json').read_text());base=root/'R01' if name=='old_full' else root/'candidate'
        phases=sum(json.loads((base/p/'phase-outcome.json').read_text())['seconds'] for p in phase_names)
        totals[name]=dict(wrapper_seconds=result['seconds'],recorded_phase_seconds=phases,
            outside_recorded_phases_seconds=result['seconds']-phases,
            outside_breakdown_known=False,scope='Different work scopes: old includes C1, new reuses C1. Residual mixes local work, process/RPC lifecycle, validation and postprocessing.')
    value=dict(model_calls=0,rows=rows,totals=totals,raw_data_retained=True,no_samples_deleted=True,
        pure_provider_compute_seconds=None,queue_seconds=None,network_seconds=None,local_algorithm_total_seconds=None)
    args.out.mkdir(parents=True,exist_ok=False);(args.out/'analysis.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))


if __name__=='__main__':main()
