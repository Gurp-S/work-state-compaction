"""Explicit approved, append-only release of verified root unassigned residues."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'benchmarks')]
from native_turn_accounting import account_turn
from acceptance_matrix_v1.campaign_credits import credited_remaining
from audit_campaign_claims import audit, read, sha


def available(parent):
    """Revalidate every persisted source seal before applying existing credits."""
    state=audit(parent)
    entries={entry['claim_sha256']:entry for entry in state['claims']}
    credits=[]
    for path in sorted(parent.glob('*.claim.settlement.json')):
        credit=read(path);entry=entries.get(credit['claim_sha256'])
        if entry is None or credit['released']!=entry['own_remainder_after_child_reservations']:
            raise ValueError('settlement_claim_or_residue_changed')
        if sorted(credit['proof']['child_claims'])!=sorted(c['claim'] for c in entry['continuations']):
            raise ValueError('settled_claim_has_new_child')
        for source,expected in credit['proof']['source_sha256'].items():
            if sha(Path(source))!=expected:raise ValueError('settlement_sealed_source_changed')
        credits.append(credit)
    return credited_remaining(read(parent/'next-admission-envelope.json')['remaining_limits'],state['claims'],credits)


def verify_receipts(entry):
    own=entry['ledger']
    if (not entry['registration_hash_matches_claim'] or own['status']!='closed'
            or own['terminal_event']!='closed' or own['uncertain'] or own['tickets'] or own['inflight']):
        raise ValueError('settlement_claim_not_complete')
    source=Path(own['path'])
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        events=[(kind,identity,json.loads(raw)) for kind,identity,raw in
                db.execute('SELECT kind,identity,payload FROM events ORDER BY seq')]
    reserved=[identity for kind,identity,_ in events if kind=='reserved']
    settled=[(identity,value) for kind,identity,value in events if kind=='settled']
    if len(set(reserved))!=len(reserved) or sorted(reserved)!=sorted(i for i,_ in settled):
        raise ValueError('settlement_reserved_phase_not_settled_once')
    phases=[]
    for base,dirs,names in os.walk(entry['child']):
        dirs[:]=[d for d in dirs if d not in {'frozen-source','actor-root','.runtime','.git','node_modules'}]
        if 'phase-outcome.json' in names:
            phases.append(Path(base)/'phase-outcome.json')
        if 'live-outcome.json' in names:
            phases.append(Path(base)/'live-outcome.json')
    proofs=[];response_ids=[];tokens=0
    sources={str(source):sha(source),str(Path(entry['claim'])):entry['claim_sha256']}
    sources.update({p:sha(Path(p)) for p in entry['matching_registrations']})
    for _,settlement in settled:
        phase=settlement['phase']
        if phase.get('usage_complete') is not True or settlement['result'].get('usage_complete') is not True:
            raise ValueError('settlement_phase_usage_unknown')
        matches=[p for p in phases if read(p)==phase]
        if len(matches)!=1:
            raise ValueError('settlement_exact_phase_artifact_missing_or_duplicate')
        path=matches[0];raw_path=path.parent/'rollout.jsonl'
        raw=raw_path.read_bytes()
        if sha(raw_path)!=phase['rollout_sha256']:
            raise ValueError('settlement_rollout_changed')
        before=phase['turn_accounting']['before'];prefix=raw[:before['byte_length']]
        import hashlib
        if hashlib.sha256(prefix).hexdigest()!=before['sha256']:
            raise ValueError('settlement_rollout_prefix_changed')
        proof=account_turn(prefix,raw,thread_id=phase['thread_id'],turn_id=phase['turn_accounting']['turn_id'])
        if not proof['complete'] or proof['receipts']!=phase['receipts']:
            raise ValueError('settlement_raw_receipts_mismatch')
        receipts=phase['receipts']['response_receipts']
        response_ids.extend(r['response_id'] for r in receipts)
        tokens+=sum(r['usage']['total_tokens'] for r in receipts)
        sources.update({str(path):sha(path),str(raw_path):sha(raw_path)})
        proofs.append(dict(phase=str(path),responses=len(receipts),raw_accounting_complete=True))
    if (len(response_ids)!=len(set(response_ids)) or set(response_ids)!=set(own['response_ids'])
            or len(response_ids)!=own['responses'] or tokens!=own['tokens']):
        raise ValueError('settlement_ledger_totals_mismatch')
    # Child allocations remain held in full, including uncertain children.
    for child in entry['continuations']:
        sources[child['claim']]=child['claim_sha256']
    return dict(raw_receipt_proofs=proofs,source_sha256=sources,
                child_claims=[c['claim'] for c in entry['continuations']])


def settle(parent,rule):
    registration=read(rule)
    if registration.get('approved_by_user') is not True or registration.get('parent_sha256')!=sha(parent/'next-admission-envelope.json'):
        raise ValueError('settlement_rule_not_bound')
    state=audit(parent);credits=[];rejected=[]
    allowed=set(registration['candidate_claims'])
    for entry in state['claims']:
        if Path(entry['claim']).name not in allowed:continue
        try:proof=verify_receipts(entry)
        except (ValueError,OSError,KeyError) as error:
            rejected.append(dict(claim=entry['claim'],reason=str(error)));continue
        path=Path(entry['claim']).with_suffix('.settlement.json')
        proof['source_sha256'][str(rule)]=sha(rule)
        credit=dict(claim_sha256=entry['claim_sha256'],released=entry['own_remainder_after_child_reservations'],
            rule_sha256=sha(rule),root_claim=entry['claim'],proof=proof,
            scope='Root unassigned residue only; all direct child claims remain fully withheld.')
        if path.exists():
            existing=read(path)
            if str(rule) not in existing['proof']['source_sha256']:
                credit['proof']['source_sha256'].pop(str(rule),None)
            if existing!=credit:raise ValueError('settlement_existing_record_changed')
        else:
            with path.open('x',encoding='utf-8') as out:
                json.dump(credit,out,ensure_ascii=False,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
        credits.append(credit)
    effective=credited_remaining(read(parent/'next-admission-envelope.json')['remaining_limits'],state['claims'],credits)
    return dict(unallocated_before=state['unallocated'],unallocated_after=effective,credits=credits,
                rejected=rejected,original_claims_changed=False,new_dispatch_authorized=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--rule',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();value=settle(args.parent,args.rule)
    with args.out.open('x',encoding='utf-8') as out:json.dump(value,out,ensure_ascii=False,indent=2)
    print(json.dumps(dict(before=value['unallocated_before'],after=value['unallocated_after'],
                         applied=len(value['credits']),rejected=value['rejected'])))
