"""Read-only allocation audit. Never refunds, authorizes or dispatches work."""
import argparse
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.campaign_allocation import remaining


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT state FROM current WHERE singleton=1').fetchone()[0])
        terminal = db.execute('SELECT kind FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0]
    budget = state['budget']
    study = budget['study']
    return dict(path=str(path), sha256=sha(path), status=state['status'], terminal_event=terminal,
                uncertain=study['uncertain'], inflight=len(budget['inflight']),
                tickets=len(state['tickets']), tokens=study['tokens'], responses=study['responses'],
                active_seconds=state['active_seconds'], response_ids=budget['response_ids'],
                scope='Ledger accounting only; not independent verification of provider billing')


def inspect_claim(path, *, nested=False, seen=None):
    seen = set() if seen is None else seen
    claim = read(path)
    child = Path(claim['child'])
    identity = str(child.resolve()).casefold()
    if identity in seen:
        raise ValueError('claim_cycle_or_duplicate_child')
    seen.add(identity)
    candidates = [child/'coordinator-private'/name for name in
                  ('ledger.db', 'live-ledger.db', 'controls-ledger.db')]
    found = [p for p in candidates if p.is_file()]
    if len(found) != 1:
        raise ValueError('canonical_claim_ledger_missing_or_ambiguous:'+str(path))
    entry = dict(claim=str(path), claim_sha256=sha(path), limits=claim['limits'],
                 nested=nested, ledger=ledger(found[0]), child=str(child))
    registrations = [child/'registration.json', child/'controls-registration.json',
                     child/'coordinator-private/registration.json',
                     child/'coordinator-private/live-registration.json']
    entry['matching_registrations'] = [str(p) for p in registrations
        if p.is_file() and sha(p) == claim.get('registration_sha256')]
    entry['registration_hash_matches_claim'] = bool(entry['matching_registrations'])
    entry['continuations'] = [inspect_claim(link, nested=True, seen=seen)
                              for link in sorted(child.glob('*.claim.json'))]
    entries = [entry['ledger']]
    def collect(value):
        entries.append(value['ledger'])
        for descendant in value['continuations']:
            collect(descendant)
    for continuation in entry['continuations']:
        collect(continuation)
    ids = [i for value in entries for i in value['response_ids']]
    entry['duplicate_receipts_across_continuations'] = len(ids) != len(set(ids))
    entry['all_ledgers_closed_and_certain'] = all(v['status'] == 'closed'
        and v['terminal_event'] == 'closed' and not v['uncertain'] and not v['inflight']
        and not v['tickets'] for v in entries)
    entry['known_tokens'] = sum(v['tokens'] for v in entries)
    entry['known_responses'] = sum(v['responses'] for v in entries)
    # Sum is conservative for possible cross-ledger overlap, never a wall-time claim.
    entry['summed_active_seconds'] = sum(v['active_seconds'] for v in entries)
    entry['arithmetic_unused_if_usage_verified'] = {
        'max_total_tokens': max(0, claim['limits']['max_total_tokens']-entry['known_tokens']),
        'max_responses': max(0, claim['limits']['max_responses']-entry['known_responses']),
        'max_seconds': max(0, math.floor(claim['limits']['max_seconds']-entry['summed_active_seconds']))}
    # Uncertain descendants retain their WHOLE allocation, not their known spend.
    own = entry['ledger']
    entry['own_remainder_after_child_reservations'] = remaining(claim['limits'], [
        dict(max_total_tokens=own['tokens'], max_responses=own['responses'],
             max_seconds=math.ceil(own['active_seconds'])),
        *[c['limits'] for c in entry['continuations']]])
    entry['refund_authorized'] = False
    return entry


def audit(parent):
    envelope = parent/'next-admission-envelope.json'
    seen = set()
    entries = [inspect_claim(p, seen=seen) for p in sorted(parent.glob('matrix-*.claim.json'))]
    for entry in entries:
        if read(Path(entry['claim']))['parent_sha256'] != sha(envelope):
            raise ValueError('claim_parent_changed')
    unallocated = remaining(read(envelope)['remaining_limits'], [e['limits'] for e in entries])
    return dict(parent=str(envelope), parent_sha256=sha(envelope), claims=entries,
                unallocated=unallocated, refunds_applied=[], dispatch_authorized=False,
                scope='No automatic release of reservations. Closed is not proof of complete usage; '
                      'nested continuations already consume their parent allocation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.parent)
    with args.out.open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(dict(claims=len(result['claims']), unallocated=result['unallocated'],
                          refunds_applied=[])))
