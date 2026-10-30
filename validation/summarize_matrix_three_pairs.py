"""Deterministic paired metrics; tiny, correlated samples remain exploratory."""
import argparse
from itertools import product
from math import comb,sqrt
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'experiments'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import inspect_ledger
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.paired_cell import save
from run_matrix_first_slice import file_hash


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def run_metrics(audit,identity,oracle):
    state=audit['state'];spec=state['runs'][identity]
    tickets={row['identity']:row['payload'] for row in audit['events'] if row['kind']=='reserved'}
    phases={tickets[row['identity']]['phase_id']:row['payload']['phase'] for row in audit['events']
        if row['kind']=='settled' and tickets[row['identity']]['run_id']==identity}
    metrics={};totals={key:0 for key in ('uncached_input_tokens','cached_input_tokens','output_tokens','total_tokens','responses')}
    for name,value in phases.items():
        usage=value['receipts']['all_usage']
        metric=dict(uncached_input_tokens=usage['input_tokens']-usage['cached_input_tokens'],
            cached_input_tokens=usage['cached_input_tokens'],output_tokens=usage['output_tokens'],
            total_tokens=usage['total_tokens'],responses=value['receipts']['response_count'],
            seconds=value['seconds'],usage_complete=value['usage_complete'])
        metrics[name]=metric
        for key in totals:totals[key]+=metric[key]
    result=spec.get('result') or {}
    continuation=phases.get('continuation')
    rows=continuation['receipts']['response_receipts'] if continuation else []
    return dict(status=spec['status'],started=spec['status']!='planned',task_success=result.get('task_success'),
        run_success=result.get('run_success'),checks_passed=sum(row['passed'] for row in result['checks']) if 'checks' in result else None,
        constraint_violations=result.get('constraint_violations'),phases=metrics,totals=totals,
        host_inclusive_seconds=state['budget']['arms'][identity]['seconds'],
        first_continuation_input=rows[0]['usage']['input_tokens'] if rows else None,
        mean_continuation_input=statistics.mean(row['usage']['input_tokens'] for row in rows) if rows else None,
        structured_evidence=score_final(continuation,oracle) if continuation else None,
        complete_usage=bool(phases) and all(value.get('usage_complete') is True for value in phases.values()))


def percentile(values,fraction):
    ordered=sorted(values);position=(len(ordered)-1)*fraction;lower=int(position);upper=min(lower+1,len(ordered)-1)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def summarize(out,*,extended=False):
    plan=read(out/'registration.json');base=Path(plan['baseline']);oracle=read(plan['oracle_path'])
    if file_hash(plan['oracle_path'])!=plan['source_sha256'][plan['oracle_path']]:raise ValueError('oracle_changed')
    audits=[inspect_ledger(base/'coordinator-private/ledger.db'),inspect_ledger(out/'coordinator-private/ledger.db')]
    if any(audit['state']['status']!='closed' for audit in audits):raise ValueError('all_groups_must_be_closed')
    pairs={}
    for label,audit,prefix in [('r1',audits[0],'')]+[(label,audits[1],label+':') for label in plan['pairs']]:
        row={name:run_metrics(audit,prefix+name,oracle) for name in ('C','Bprime')}
        valid=all(row[name]['run_success'] and row[name]['complete_usage'] for name in row)
        row['valid_pair']=bool(valid)
        row['C_over_B_token_ratio']=row['C']['totals']['total_tokens']/row['Bprime']['totals']['total_tokens'] if valid else None
        pairs[label]=row
    report=dict(pairs=pairs,attempted_pairs=len(pairs),valid_pairs=sum(row['valid_pair'] for row in pairs.values()),
        current_repetition_group_known_tokens=audits[1]['state']['budget']['study']['tokens'],
        current_repetition_group_known_responses=audits[1]['state']['budget']['study']['responses'],
        current_repetition_group_usage_complete=not audits[1]['state']['budget']['study']['uncertain'],
        current_repetition_group_active_seconds=audits[1]['state']['active_seconds'],
        historical_failures_preserved=True,whole_campaign_usage_complete=False,
        uncertainty_scope='n=3, uncontrolled sampling/cache and changed concurrency; no confirmatory population-level inference.')
    if all(row['valid_pair'] for row in pairs.values()):
        aggregates={}
        for name in ('C','Bprime'):
            rows=[row[name] for row in pairs.values()]
            totals={key:sum(row['totals'][key] for row in rows) for key in rows[0]['totals']}
            aggregates[name]=dict(totals=totals,mean_total_tokens=totals['total_tokens']/len(rows),
                total_token_range=[min(row['totals']['total_tokens'] for row in rows),max(row['totals']['total_tokens'] for row in rows)],
                mean_host_inclusive_seconds=statistics.mean(row['host_inclusive_seconds'] for row in rows),
                successful_tasks=sum(row['task_success'] is True for row in rows),
                cost_per_successful_task_tokens=totals['total_tokens']/sum(row['task_success'] is True for row in rows))
        report['aggregates']=aggregates
        report['C_over_B_aggregate_token_ratio']=aggregates['C']['totals']['total_tokens']/aggregates['Bprime']['totals']['total_tokens']
        report['C_raw_token_wins']=sum(row['C_over_B_token_ratio']<1 for row in pairs.values())
        samples=list(pairs.values());ratios=[]
        for choices in product(range(len(samples)),repeat=len(samples)):
            ratios.append(sum(samples[i]['C']['totals']['total_tokens'] for i in choices)/sum(samples[i]['Bprime']['totals']['total_tokens'] for i in choices))
        report['exploratory_paired_bootstrap']=dict(resamples=len(ratios),percentile_95_ratio_interval=[percentile(ratios,.025),percentile(ratios,.975)],
            interpretation='Exact enumeration of resamples of these three observations only. Does not account for shared caches or concurrency dependence; not proof of stable superiority.')
        differences=[row['C']['totals']['total_tokens']-row['Bprime']['totals']['total_tokens'] for row in samples]
        mean=statistics.mean(differences)
        half=4.3026527299*statistics.stdev(differences)/sqrt(3)
        wins=sum(d<0 for d in differences);losses=sum(d>0 for d in differences);n=wins+losses
        p=min(1.,2*sum(comb(n,k) for k in range(min(wins,losses)+1))/2**n) if n else 1.
        report['small_sample_checks']=dict(paired_mean_token_difference=mean,
            exploratory_t95_difference_interval=[mean-half,mean+half],two_sided_sign_test_p=p,
            assumptions='t interval needs independent approximately normal paired differences; sign test needs independent pairs. These assumptions are not verified under shared caches and changed concurrency.',
            conclusion='No confirmatory stable-superiority claim. The n=3 percentile bootstrap may be misleadingly narrow and is not the primary interval.')
    save(out/('three-pair-metrics-v2.json' if extended else 'three-pair-metrics.json'),report)
    print(json.dumps({k:report[k] for k in ('attempted_pairs','valid_pairs','current_repetition_group_known_tokens','current_repetition_group_usage_complete')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--extended',action='store_true')
    args=parser.parse_args();summarize(args.out.resolve(),extended=args.extended)
