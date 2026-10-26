"""Close the actual first wave, retaining unknowns; replay budget allocation."""
from datetime import datetime,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,FIELDS
from native_rollout_snapshot import parse_rollout
from native_phase_budget import PhaseBudget
from native_application_budget_policy import shared_arm_allocation

AREA=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')
reg=read(AREA/'registration.json')
assert all(file_hash(path)==value for path,value in reg['pins'].items())
ledger=read(AREA/'wave-0-ledger.json')['snapshot']
assert not ledger['inflight']
proposal=shared_arm_allocation(reg['conditions']['budgets'])
assert proposal['per_arm']==reg['conditions']['budgets']['per_arm']
assert proposal['study']==reg['conditions']['budgets']['study']
assert proposal['boundary_phase']==reg['conditions']['budgets']['boundary_phase']
arms={}
ids=set()
total=dict.fromkeys(FIELDS,0)
for task in ('a3','collaboration'):
    for arm in ('B','C'):
        output=AREA/'trajectories'/task/'r1'/arm/'output'
        worker=read(output/'worker-result.json')
        phase=read(output/'S1-phase/phase-outcome.json')
        assert worker['admission_matched'] and len(worker['phases'])==1
        assert all(item['empty_confirmed'] for item in worker['cleanup'])
        closed=(output/'final-threads/000.jsonl').read_bytes()
        snap=parse_rollout(closed)
        assert snap.metadata['parse_complete']
        phase_raw=(output/'S1-phase/rollout.jsonl').read_bytes()
        assert closed.startswith(phase_raw)
        records=[row['payload'] for row in snap.rows if row['type']=='token_usage_record']
        actual={row['response_id']:row['usage'] for row in records}
        expected={row['response_id']:row['usage'] for row in phase['receipts']['response_receipts']}
        assert actual==expected and len(actual)==len(records)
        assert not ids.intersection(actual)
        ids.update(actual)
        for receipt in actual.values():
            for key in FIELDS:
                total[key]+=receipt[key]
        aborted=[row['payload'] for row in snap.rows if row['type']=='event_msg' and row['payload'].get('type')=='turn_aborted']
        assert len(aborted)==1 and aborted[0]['turn_id']==phase['turn_accounting']['turn_id']
        assert phase['failure']=='registered_token_cap' and not phase['usage_complete']
        before=PhaseBudget.resolve(dict(phase_budget=reg['conditions']['budgets']['ordinary_phase']),begin=0,deadline=600)
        after=PhaseBudget.resolve(dict(phase_budget=proposal['ordinary_phase']),begin=0,deadline=600)
        assert before.stop_reason(phase['receipts'])=='registered_token_cap'
        assert after.stop_reason(phase['receipts']) is None
        arms[task+'/'+arm]=dict(responses=len(actual),known_usage=phase['receipts']['all_usage'],seconds=phase['seconds'],
            source_phase=str(output/'S1-phase/phase-outcome.json'),source_phase_sha256=file_hash(output/'S1-phase/phase-outcome.json'),
            closed_sha256=snap.metadata['sha256'],closed_receipts_match=True,owned_processes_empty=True,
            failure=phase['failure'],usage_complete=False,completion_reasons=phase['usage_completion_evidence']['reasons'],
            before_prefix_verdict='registered_token_cap',after_prefix_verdict='not_yet_at_cap',
            after_task_completion='unobserved',compression_boundaries_executed=0)
assert len(ids)==ledger['study']['responses'] and total['total_tokens']==ledger['study']['tokens']
result=dict(captured_at=datetime.now(timezone.utc).isoformat(),arms=arms,known_responses=len(ids),known_usage=total,
    complete_usage=None,cash=None,ledger_uncertain=ledger['study']['uncertain'],
    all_owned_processes_empty=True,remaining_registered_pairs_not_run=13,formal_valid_pairs=0,
    replay_new_model_calls=0,original_failure_preserved=True,
    budget_proposal=proposal,proposal_ready_to_launch=False,
    proposal_limits=['Replay only removes the observed token-cap stop on these exact prefixes; completion is unobserved',
        'Original study stays frozen with uncertain usage; no reset of its ledger or silent continuation',
        'A qualified uninterrupted pilot with actual boundaries and closed accounting is still required'],
    implementation_sha256=file_hash(ROOT/'experiments/native_application_budget_policy.py'))
save(HERE/'first-wave-review.json',result)
save(HERE/'study-conditions-v4-proposed.json',dict(kind='proposal_not_launched',ready_to_launch=False,
    original_registration=str(AREA/'registration.json'),original_registration_sha256=file_hash(AREA/'registration.json'),
    budgets=proposal,original_known_usage=total,original_complete_usage=None,
    original_ledger_frozen=True,qualification_required='Uninterrupted task and actual B/C boundaries; preserve prior known spend and uncertainty'))
print(dict(known_responses=len(ids),known_tokens=total['total_tokens'],complete_usage=None,
    formal_valid_pairs=0,remaining_pairs=13,replay_new_model_calls=0,proposal_ready_to_launch=False))
