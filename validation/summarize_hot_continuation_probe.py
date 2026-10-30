"""Keep interrupted samples and distinguish continuation from full-chain costs."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import inspect_ledger
from acceptance_matrix_v1.paired_cell import save
from run_matrix_first_slice import file_hash


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def metrics(phase):
    rows=phase['receipts']['response_receipts'];usage=phase['receipts']['all_usage']
    return dict(completed=phase['completed'],failure=phase['failure'],usage_complete=phase['usage_complete'],
        first_input_tokens=rows[0]['usage']['input_tokens'] if rows else None,observed_usage=usage,
        response_receipts=len(rows),native_seconds=phase['seconds'])


def summarize(out):
    plan=read(out/'registration.json');state=inspect_ledger(out/'coordinator-private/ledger.db')['state']
    if state['status']!='closed':raise ValueError('probe_not_closed')
    closure=read(out/'closure.json');evidence=read(out/'structured-evidence.json');rows={}
    for name,proof in plan['proof'].items():
        old=metrics(read(proof['old_continuation']));folder=out/name/'coordinator-private/C'
        phase=read(folder/'continuation/phase-outcome.json');new=metrics(phase);result=closure['results'][name]
        rows[name]=dict(old=old,new=new,task_success=result.get('task_success'),run_success=result.get('run_success'),
            code_checks_passed=sum(row['passed'] for row in result.get('checks',[])),constraint_violations=result.get('constraint_violations'),
            exact_answer_correct=evidence[name]['exact_answer_correct'],citation_byte_matches=evidence[name]['citation_byte_matches'],
            first_input_delta=new['first_input_tokens']-old['first_input_tokens'],
            first_input_ratio=new['first_input_tokens']/old['first_input_tokens'],
            provider_error_codes=[notice.get('error',{}).get('codexErrorInfo') for notice in phase.get('retry_notices',[])],
            historical_selection_usage_retained=proof['reuse']['original_selection_usage'])
    value=dict(status='closed_probe_not_promoted',samples=rows,new_known_tokens=state['budget']['study']['tokens'],
        new_known_response_receipts=state['budget']['study']['responses'],new_usage_complete=not state['budget']['study']['uncertain'],
        active_seconds=state['active_seconds'],old_controls_rerun=False,new_selector_calls=0,
        original_budget_limits=state['budget']['study']['limits'],old_failures_and_unknowns_preserved=True,
        cumulative_known_tokens_lower_bound=3745397+state['budget']['study']['tokens'],
        cumulative_known_response_receipts=105+state['budget']['study']['responses'],
        whole_campaign_usage_complete=False,default_hot_projection_enabled=False,
        performance_conclusion='Two first inputs smaller, one larger; bootstrap blocks differ. No stable full-request or full-chain cost benefit established.',
        recovery_and_parent_decision='Keep previous fully qualified indexed C for denoise comparison; retain hot as unpromoted sidecar.',
        source_receipts=dict(registration_sha256=file_hash(out/'registration.json'),closure_sha256=file_hash(out/'closure.json'),ledger_sha256=file_hash(out/'coordinator-private/ledger.db')))
    save(out/'diagnostic-metrics.json',value)
    print(json.dumps({k:value[k] for k in ('status','new_known_tokens','new_known_response_receipts','new_usage_complete','active_seconds')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    summarize(parser.parse_args().out.resolve())
