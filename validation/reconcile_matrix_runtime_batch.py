"""Derived per-run evidence; original failed ledger/results remain unchanged."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import inspect_ledger
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.paired_cell import save
from native_rollout_snapshot import capture_rollout
from run_matrix_first_slice import file_hash


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def reconcile(out):
    plan=read(out/'registration.json');private=out/'coordinator-private'
    audit=inspect_ledger(private/'ledger.db');budget=audit['state']
    if budget['status']!='closed':raise ValueError('batch_not_closed')
    snapshots={}
    for index,(name,digest) in enumerate(plan['source_sha256'].items()):
        original=Path(name)
        try:relative=original.relative_to(ROOT)
        except ValueError:relative=Path('external')/(str(index)+'-'+original.name)
        frozen=private/'frozen-source'/relative
        if file_hash(frozen)!=digest:raise ValueError('frozen_source_changed')
    for name in ('A','last-state-only'):
        folder=private/name/'native-session'
        cleanup=read(folder/'process-cleanup.json')
        if cleanup.get('empty_confirmed') is not True:raise ValueError('process_cleanup_unconfirmed')
        snapshot=capture_rollout(read(folder/'opened.json')['thread']['path'],archive=folder/'closed-reconciliation.jsonl')
        if not snapshot.metadata['parse_complete']:raise ValueError('closed_history_unverifiable')
        rows=[row['payload'] for row in snapshot.rows if row.get('type')=='token_usage_record']
        snapshots[name]=dict(metadata=snapshot.metadata,usage_rows=rows)
    name='last-state-only'
    tickets={event['identity'] for event in audit['events'] if event['kind']=='reserved' and event['payload']['run_id']==name}
    if len(tickets)!=1 or any(event['kind']=='input_bound' and event['identity'] in tickets for event in audit['events']):
        raise ValueError('no_history_dispatch_not_excluded')
    if snapshots[name]['usage_rows'] or (private/name/'continuation/phase-outcome.json').exists():
        raise ValueError('unexpected_no_history_phase_or_usage')
    phase=read(private/'A/continuation/phase-outcome.json')
    if phase.get('completed') is not True or phase.get('failure') or phase.get('usage_complete') is not True:
        raise ValueError('A_phase_not_complete')
    recorded={row['response_id']:row['usage'] for row in phase['receipts']['response_receipts']}
    closed={row['response_id']:row['usage'] for row in snapshots['A']['usage_rows']}
    if recorded!=closed or len(closed)!=len(snapshots['A']['usage_rows']):raise ValueError('A_closed_receipts_changed')
    usage=phase['receipts']['all_usage'];study=budget['budget']['study']
    if study['tokens']!=usage['total_tokens'] or study['responses']!=len(recorded):raise ValueError('ledger_known_usage_changed')
    oracle=read(plan['oracle_path'])
    if file_hash(plan['oracle_path'])!=plan['source_sha256'][plan['oracle_path']]:raise ValueError('oracle_changed')
    corrected=score_final(phase,oracle)
    receipt=dict(status='per_run_usage_reconciled',local_batch_usage_complete=True,original_ledger_unknown_preserved=True,
        whole_campaign_usage_complete=False,earlier_unknowns_preserved=True,
        known_tokens=usage['total_tokens'],known_responses=len(recorded),active_seconds=budget['active_seconds'],
        A_phase_completed=True,A_code_checks_passed=sum(row['passed'] for row in read(private/'A/result.json')['checks']),
        no_history_model_dispatch=False,no_history_task_result=None,failure_classification='F5',
        corrected_structured_evidence=corrected,original_structured_evidence_sha256=file_hash(out/'structured-evidence.json'),
        ledger_sha256=file_hash(private/'ledger.db'),closure_sha256=file_hash(out/'closure.json'),closed_histories=snapshots,
        arithmetic_remainder=dict(max_total_tokens=plan['limits']['max_total_tokens']-study['tokens'],
            max_responses=plan['limits']['max_responses']-study['responses'],
            max_seconds=max(0,int(plan['limits']['max_seconds']-budget['active_seconds']))),
        automatic_dispatch_authorized=False,
        scope='A complete six receipts plus proven no-dispatch empty-history failure. No C/B execution or valid history-dependence comparison.')
    save(out/'per-run-reconciliation.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('status','known_tokens','known_responses','active_seconds','arithmetic_remainder')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    reconcile(parser.parse_args().out.resolve())
