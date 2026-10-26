"""Seal the failed qualification and its browser capability diagnosis."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,FIELDS
from native_rollout_snapshot import parse_rollout

AREA=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1')
result=read(AREA/'result.json')
assert not result['ledger']['inflight'] and result['ledger']['study']['uncertain']
total=dict.fromkeys(FIELDS,0)
ids=set()
arms={}
for arm in ('B','C'):
    output=AREA/'arms'/arm/'output'
    worker=read(output/'worker-result.json')
    phase=read(output/'S1-phase/phase-outcome.json')
    assert worker['admission_matched'] and len(worker['phases'])==1
    assert phase['failure']=='registered_response_cap' and not phase['usage_complete']
    assert all(item['empty_confirmed'] for item in worker['cleanup'])
    closed=output/'final-threads/000.jsonl'
    rows=parse_rollout(closed.read_bytes())
    assert rows.metadata['parse_complete']
    actual={row['payload']['response_id']:row['payload']['usage'] for row in rows.rows if row['type']=='token_usage_record'}
    expected={row['response_id']:row['usage'] for row in phase['receipts']['response_receipts']}
    assert actual==expected and not (set(actual)&ids)
    ids.update(actual)
    assert not any(row['type']=='compacted' for row in rows.rows)
    native=Path(read(output/'initial/thread-start.json')['thread']['path'])
    assert native.read_bytes()==closed.read_bytes()
    for usage in actual.values():
        for key in FIELDS:
            total[key]+=usage[key]
    arms[arm]=dict(phase_sha256=file_hash(output/'S1-phase/phase-outcome.json'),closed_sha256=file_hash(closed),
        known_usage=phase['receipts']['all_usage'],responses=len(actual),failure=phase['failure'],
        complete_usage=None,compression_boundaries=0,owned_processes_empty=True)
assert len(ids)==result['ledger']['study']['responses'] and total['total_tokens']==result['ledger']['study']['tokens']
browser=Path('D:/agent-task-runs/wsc-browser-capability-20261025-v1')
before=read(browser/'result.json')
after=read(browser/'local-browser-result.json')
assert before['observations']['parent-default']['passed']
assert not before['observations']['native_workspace-default']['passed']
assert after['observations']['default']['passed'] and after['observations']['full']['passed']
assert before['model_calls']==after['model_calls']==0
assert before['cleanup']['empty_confirmed'] and after['cleanup']['empty_confirmed']
live=read(Path('D:/agent-task-runs/wsc-browser-model-route-20261025-v1/result.json'))
assert live['browser_result']['passed'] and live['cleanup']['empty_confirmed']
save(HERE/'a3-first-qualification-review.json',dict(arms=arms,known_usage=total,known_responses=len(ids),
    complete_usage=None,formal_valid_pairs=0,remaining_formal_pairs_not_run=13,formal_valid_pairs_still_required=15,
    browser_before='Same script outside native succeeds; native default cache fails EPERM',
    browser_after='Same binary bytes inside private workspace launch, navigate loopback and screenshot',
    browser_model_route_passed=True,browser_model_turn_complete=False,
    browser_model_known_usage=live['phase']['receipts']['all_usage'],
    browser_model_known_responses=live['phase']['receipts']['response_count'],browser_model_complete_usage=None,
    new_model_calls_in_this_review=0,all_owned_processes_empty=True,
    executed_source_version=read(HERE/'a3-runtime-delivery.json')))
print(dict(known_responses=len(ids),known_tokens=total['total_tokens'],formal_valid_pairs=0,
    browser_model_route_passed=True,complete_usage=None))
