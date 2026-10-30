"""Derive a no-inference receipt without altering the failed closed ledger."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'experiments'),str(ROOT/'validation')]
from acceptance_matrix_v1.dispatch_budget import inspect_ledger
from acceptance_matrix_v1.paired_cell import save
from native_rollout_snapshot import capture_rollout
from run_matrix_first_slice import file_hash


def reconcile(out):
    plan=json.loads((out/'registration.json').read_text(encoding='utf-8'))
    audit=inspect_ledger(out/'coordinator-private/ledger.db')
    if audit['state']['status']!='closed' or any(e['kind']=='input_bound' for e in audit['events']):
        raise ValueError('not_a_closed_pre_dispatch_failure')
    if audit['state']['budget']['study']['tokens'] or audit['state']['budget']['study']['responses']:
        raise ValueError('model_usage_present')
    if list((out/'coordinator-private').rglob('phase-outcome.json')):
        raise ValueError('native_phase_was_entered')
    sources={}
    for name,digest in plan['source_sha256'].items():
        original=Path(name)
        copy=out/'coordinator-private/frozen-source'/original.relative_to(ROOT.parent)
        if file_hash(copy)!=digest:raise ValueError('failed_source_snapshot_changed')
        sources[str(copy)]=digest
    cleanups=list((out/'coordinator-private').rglob('process-cleanup.json'))
    if len(cleanups)!=2 or any(json.loads(p.read_text(encoding='utf-8')).get('empty_confirmed') is not True for p in cleanups):
        raise ValueError('native_cleanup_not_verified')
    histories=[]
    for opened in (out/'coordinator-private').rglob('opened.json'):
        thread=json.loads(opened.read_text(encoding='utf-8'))['thread']
        snapshot=capture_rollout(thread['path'],archive=opened.parent/'closed-no-dispatch.jsonl')
        if not snapshot.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snapshot.rows):
            raise ValueError('usage_or_unclosed_history_present')
        histories.append(snapshot.metadata)
    if len(histories)!=1:raise ValueError('unexpected_opened_threads')
    closure=json.loads((out/'closure.json').read_text(encoding='utf-8'))
    receipt=dict(status='verified_no_model_dispatch',local_usage_complete=True,known_tokens=0,known_responses=0,
        original_unknown_ledger_preserved=True,original_failed_results_preserved=True,
        failure_classifications={'Bprime':'F5','C':'F5'},remaining_first_batch_limits=closure['remaining_first_batch_limits'],
        activity_seconds=closure['budget']['active_seconds'],ledger_sha256=file_hash(out/'coordinator-private/ledger.db'),
        closure_sha256=file_hash(out/'closure.json'),source_snapshots=sources,closed_histories=histories,
        scope='No input-bound event before any model API in the frozen cell; no phase entered; owned processes closed; zero usage records. Not complete historical campaign accounting.')
    save(out/'no-dispatch-reconciliation.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('status','known_tokens','known_responses','activity_seconds','remaining_first_batch_limits')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    reconcile(parser.parse_args().out.resolve())
