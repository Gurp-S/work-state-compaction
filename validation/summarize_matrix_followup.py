"""Observable metrics for a closed admission group, without a model judge."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'experiments'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import inspect_ledger
from acceptance_matrix_v1.paired_cell import save
from run_matrix_first_slice import file_hash


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def timing(out,audit):
    tickets={row['identity']:row['payload'] for row in audit['events'] if row['kind']=='reserved'}
    phases=[dict(arm=tickets[row['identity']]['run_id'],phase=tickets[row['identity']]['phase_id'],
        host_inclusive_seconds=row['payload']['result']['active_phase_seconds'])
        for row in audit['events'] if row['kind']=='settled']
    tools={}
    for name in ('C','Bprime'):
        counts={}
        for path in (out/'coordinator-private'/name).glob('*/events.jsonl'):
            for line in path.read_text(encoding='utf-8').splitlines():
                event=json.loads(line)
                if event.get('method')!='item/completed':continue
                item=event['params']['item'];kind=item['type']
                if kind not in ('commandExecution','dynamicToolCall'):continue
                count=counts.setdefault(kind,dict(count=0,duration_ms_sum=0,duration_missing=0))
                count['count']+=1
                if type(item.get('durationMs')) is int:count['duration_ms_sum']+=item['durationMs']
                else:count['duration_missing']+=1
        tools[name]=counts
    return dict(phases=phases,tools=tools,
        scope='Observed intervals and tool counters. Tool sums may overlap; not CPU time or remote inference/queue decomposition.')


def summarize(out):
    plan=read(out/'registration.json');closure=read(out/'closure.json')
    audit=inspect_ledger(out/'coordinator-private/ledger.db');state=audit['state']
    if state['status']!='closed':raise ValueError('metrics_require_closed_group')
    report=dict(status='closed_group',model=plan['model'],executable_sha256=plan['executable_sha256'],
        comparison=plan['comparison'],valid_pair=closure['valid_pair'],
        current_history_dependency_qualified=closure['history_dependency_qualified'],arms={},
        current_group_usage_complete=not state['budget']['study']['uncertain'],
        known_tokens=state['budget']['study']['tokens'],known_responses=state['budget']['study']['responses'],
        active_union_seconds=state['active_seconds'],whole_campaign_usage_complete=False,
        old_failures_and_unknowns_preserved=True,unobserved_internal_costs=None,
        scope='One strong-model T1 admission group. No confidence interval or stable superiority claim.')
    for name,spec in state['runs'].items():
        folder=out/'coordinator-private'/name
        phases={}
        for path in sorted(folder.glob('*/phase-outcome.json')):
            value=read(path);usage=value['receipts']['all_usage']
            phases[path.parent.name]=dict(completed=value['completed'],failure=value.get('failure'),
                usage_complete=value['usage_complete'],observed_seconds=value['seconds'],
                input_tokens=usage['input_tokens'],cached_input_tokens=usage['cached_input_tokens'],
                uncached_input_tokens=usage['input_tokens']-usage['cached_input_tokens'],
                output_tokens=usage['output_tokens'],reasoning_output_tokens=usage['reasoning_output_tokens'],
                total_tokens=usage['total_tokens'],response_receipts=value['receipts']['response_count'])
        result=closure['results'].get(name)
        arm=dict(status=spec['status'],task_success=result.get('task_success') if result else None,
            run_success=result.get('run_success') if result else None,
            checks_passed=sum(v['passed'] for v in result.get('checks',[])) if result else None,
            constraint_violations=result.get('constraint_violations') if result else None,
            phases=phases,host_inclusive_seconds=state['budget']['arms'][name]['seconds'])
        if result and 'error' in result:arm['error']=result['error']
        report['arms'][name]=arm
    report['structured_evidence']=read(out/'structured-evidence.json')
    if closure['valid_pair']:
        c=state['budget']['arms']['C']['tokens'];b=state['budget']['arms']['Bprime']['tokens']
        report['observed_C_over_B_token_ratio']=c/b if b else None
        report['C_minus_B_observed_tokens']=c-b
    else:
        report['observed_C_over_B_token_ratio']=None
    recovery=out/'coordinator-private/C/recovery.json'
    if recovery.exists():
        value=read(recovery)
        report['C_recovery']={k:value[k] for k in ('calls','refused_callbacks','rows_verified','text_bytes_examined')}
    proof=out/'coordinator-private/Bprime/compression-proof.json'
    report['native_compression_proof']=read(proof) if proof.exists() else None
    report['source_receipts']=dict(registration_sha256=file_hash(out/'registration.json'),
        closure_sha256=file_hash(out/'closure.json'),ledger_sha256=file_hash(out/'coordinator-private/ledger.db'))
    save(out/'observable-metrics.json',report)
    print(json.dumps({k:report[k] for k in ('valid_pair','known_tokens','known_responses','current_group_usage_complete','observed_C_over_B_token_ratio')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    summarize(parser.parse_args().out.resolve())
