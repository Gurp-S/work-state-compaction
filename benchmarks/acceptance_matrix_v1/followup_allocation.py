"""Validate a closed local reconciliation before reserving its residual once."""
import json
from pathlib import Path
from .workspace_runtime import digest
from .campaign_allocation import remaining


def followup(parent):
    parent=Path(parent)
    receipt_path=parent/'per-run-reconciliation.json'
    receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('status')!='per_run_usage_reconciled' or receipt.get('local_batch_usage_complete') is not True:
        raise ValueError('followup_usage_not_reconciled')
    for path,key in ((parent/'closure.json','closure_sha256'),(parent/'coordinator-private/ledger.db','ledger_sha256')):
        if digest(path)!=receipt[key]:raise ValueError('followup_closed_source_changed')
    closure=json.loads((parent/'closure.json').read_text(encoding='utf-8'))['budget']
    study=closure['budget']['study']
    if closure['status']!='closed' or study['tokens']!=receipt['known_tokens'] or study['responses']!=receipt['known_responses']:
        raise ValueError('followup_known_usage_changed')
    expected=dict(max_total_tokens=study['limits']['max_total_tokens']-study['tokens'],
        max_responses=study['limits']['max_responses']-study['responses'],
        max_seconds=max(0,int(study['limits']['max_seconds']-closure['active_seconds'])))
    if expected!=receipt['arithmetic_remainder']:raise ValueError('followup_remainder_changed')
    claim=parent/'next-runtime-group.claim.json'
    if claim.exists():raise ValueError('followup_already_claimed')
    baseline=dict(max_total_tokens=350000,max_responses=14,max_seconds=600)
    paired=dict(max_total_tokens=500000,max_responses=14,max_seconds=800)
    runs={'A':dict(baseline),'last-state-only':dict(baseline),'Bprime':dict(paired),'C':dict(paired)}
    limits=receipt['arithmetic_remainder']
    # Tokens/responses are additive; time is baseline parallel union plus C/B.
    held=dict(max_total_tokens=sum(v['max_total_tokens'] for v in runs.values()),
        max_responses=sum(v['max_responses'] for v in runs.values()),
        max_seconds=baseline['max_seconds']+2*paired['max_seconds'])
    remaining(limits,[held])
    return dict(reference=receipt_path,parent_claim=claim,limits=limits,run_limits=runs,
        extra_sources=[parent/'closure.json',parent/'coordinator-private/ledger.db',parent/'registration.json'])
