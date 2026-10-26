"""Small, separately registered model delivery using exact existing check facts."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, usage
from native_review_capsule import verify, open_receiver
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope
from native_rollout_snapshot import capture_rollout
from native_cold_access import _check

PRIOR = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
S3 = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')
OUT = Path('D:/agent-task-runs/wsc-a3-capsule-review-20261026-v1')


def execute():
    OUT.mkdir(exist_ok=False)
    old = read(PRIOR / 'result.json')
    assert old['cleanup']['empty_confirmed'] and not old['ledger']['inflight']
    hot = read(PRIOR / 'review-capsule/facts.json')
    index = verify(hot)
    reg = read(PRIOR / 'review-registration.json')['session']
    elapsed = (PRIOR / 'result.json').stat().st_mtime - (PRIOR / 'review-registration.json').stat().st_mtime
    envelope = qualification_envelope(old['ledger'], [], elapsed)
    known = (read(S3 / 'registration.json')['inherited_C_known']['tokens']
        + read(S3 / 'result.json')['ledger']['study']['tokens'] + old['ledger']['study']['tokens'])
    limits = dict(max_responses=2, max_seconds=90, max_total_tokens=60000)
    assert known + limits['max_total_tokens'] <= 6000000
    schema = dict(type='object', additionalProperties=False,
        required=['scope', 'checks_count', 'all_checks_passed', 'source_manifest_sha256', 'original_stage_status',
            'original_stage_usage_complete', 'BC_benefit_proven', 'development_history_in_capsule', 'summary_zh', 'limitations'],
        properties=dict(scope=dict(type='string'), checks_count=dict(type='integer'), all_checks_passed=dict(type='boolean'),
            source_manifest_sha256=dict(type='string'), original_stage_status=dict(type='string'),
            original_stage_usage_complete=dict(anyOf=[dict(type='boolean'), dict(type='null')]),
            BC_benefit_proven=dict(type='boolean'), development_history_in_capsule=dict(type='boolean'),
            summary_zh=dict(type='string'), limitations=dict(type='array', items=dict(type='string'))))
    request = ('请仅依据提供的、已与当前源码绑定的检查事实，生成简洁中文 S3 状态交付说明。'
        '列出检查结果、原阶段状态、完整用量是否已知、B/C 收益证据边界和未覆盖范围。'
        '本次是事实交付，不包含新增开发、重新验收或历史原因调查。按给定 JSON 格式输出。')
    pins = {str(p): file_hash(p) for p in [PRIOR / 'result.json', PRIOR / 'review-capsule/facts.json',
        Path(hot['cold_index']['path']), S3 / 'result.json', Path(__file__).resolve()]}
    pins.update({str(p): file_hash(p) for folder in ('src', 'experiments') for p in (ROOT / folder).rglob('*.py')})
    registration = dict(created_at=datetime.now(timezone.utc).isoformat(), limits=limits, envelope=envelope,
        parent_registration=str(PRIOR / 'review-registration.json'), inherited_known_chain_tokens=known,
        expected_facts=hot, pins=pins, automatic_retries=0, request=request,
        scope='Fact-only S3 status delivery; narrower than previous history-based review, not a causal cost comparison',
        whole_campaign_usage_complete=False)
    save(OUT / 'registration.json', registration)
    budget = StudyBudget({'C/capsule-review': limits}, envelope['remaining_limits'])
    session = None
    phases = []
    outcome = dict(state='preflight', scope=registration['scope'], whole_campaign_usage_complete=False)
    inference_started = False
    try:
        session = open_receiver(reg, OUT / 'receiver', hot)
        _check(session, [(hot['cold_index']['path'], hot['cold_index']['sha256']),
            *[(row['path'], row['sha256']) for row in index['receipts']]], OUT / 'cold-access')
        ticket, granted = budget.reserve('C/capsule-review', limits)
        save(OUT / 'grant.json', dict(ticket=ticket, limits=granted, ledger=budget.snapshot()))
        def record(phase):
            phases.append(phase)
            save(OUT / 'phase-journal.json', phase)
            result = budget.settle(ticket, phase)
            save(OUT / 'settlement.json', dict(settlement=result, ledger=budget.snapshot()))
        inference_started = True
        phase = session.execute_stage(request, OUT / 'phase', granted, record, output_schema=schema)
        outcome.update(state='completed' if phase['completed'] and phase['usage_complete'] and not phase['failure'] else 'incomplete',
            failure=phase['failure'], usage_complete=phase['usage_complete'])
        if outcome['state'] == 'completed':
            response = json.loads(phase['finals'][0]['text'])
            save(OUT / 'model-delivery.json', response)
            fields = ['scope', 'checks_count', 'all_checks_passed', 'source_manifest_sha256', 'original_stage_status',
                'original_stage_usage_complete', 'BC_benefit_proven', 'development_history_in_capsule']
            outcome['fact_matches'] = {key: response.get(key) == hot[key] for key in fields}
            outcome['response'] = response
    except Exception as error:
        outcome.update(state='error', error=type(error).__name__ + ':' + str(error))
        if inference_started and not phases: budget.mark_unknown('C/capsule-review')
    finally:
        if session:
            outcome['cleanup'] = session.close()
            snap = capture_rollout(session.opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
            expected = {row['response_id']: row['usage'] for phase in phases for row in phase.get('receipts', {}).get('response_receipts', [])}
            actual = {row['payload']['response_id']: row['payload']['usage'] for row in snap.rows if row['type'] == 'token_usage_record'}
            late = [row for row in snap.rows if row['type'] == 'token_usage_record' and row['payload']['response_id'] not in expected]
            if any(actual.get(key) != value for key, value in expected.items()) or late or not snap.metadata['parse_complete']:
                budget.mark_unknown('C/capsule-review', usage(late, session.opened['thread']['id'])['response_receipts'] if late else ())
                outcome['state'] = 'accounting_unknown'
            outcome['source_unchanged'] = session.source_manifest() == reg['initial_manifest']
            outcome['closed_snapshot'] = snap.metadata
        outcome['ledger'] = budget.snapshot()
        outcome['pins_unchanged'] = all(file_hash(path) == value for path, value in pins.items())
        outcome['inference_started'] = inference_started
        outcome['fact_delivery_passed'] = (outcome['state'] == 'completed' and bool(outcome.get('fact_matches'))
            and all(outcome['fact_matches'].values()) and outcome['source_unchanged'] and outcome['pins_unchanged']
            and outcome['cleanup']['empty_confirmed'] and not outcome['ledger']['study']['uncertain'])
        outcome['full_S2_to_S3_qualification_passed'] = False
        save(OUT / 'result.json', outcome)
    print({key: outcome.get(key) for key in ('state', 'failure', 'error', 'fact_delivery_passed')}, flush=True)


if __name__ == '__main__':
    execute()
