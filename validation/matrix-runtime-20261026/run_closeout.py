"""Bounded read-only delivery review of the already-tested C/S3 result."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, manifest, usage
from native_campaign_envelope import qualification_envelope
from native_application_budget import StudyBudget
from native_study_fork_session import NativeForkSession
from native_rollout_snapshot import capture_rollout

AREA = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')
COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')


def execute():
    prepared = read(AREA / 'prepared.json')
    old = read(PRIOR / 'result.json')
    old_registration = read(PRIOR / 'registration.json')
    parent = read(PRIOR / 'receiver/thread-fork.json')['thread']
    assert file_hash(parent['path']) == file_hash(PRIOR / 'closed-native.jsonl')
    assert old['cleanup']['empty_confirmed'] and not old['ledger']['inflight']
    elapsed = (PRIOR / 'result.json').stat().st_mtime - (PRIOR / 'registration.json').stat().st_mtime
    envelope = qualification_envelope(old['ledger'], [], elapsed)
    reg = {**read(AREA / 'runtime-C.json'), 'sandbox': 'read-only',
        'parent_thread_id': parent['id'], 'parent_paths': {**old_registration['session']['parent_paths'], parent['id']: parent['path']},
        'initial_manifest': old['source_manifest_after']}
    reg.pop('before_turn_id', None)
    assert manifest(Path(reg['workspace']) / 'gui/src') == prepared['current_source_manifest']
    limits = dict(max_responses=3, max_seconds=120, max_total_tokens=600000)
    source_limits = old_registration['inherited_C_known']['tokens'] + old['ledger']['study']['tokens']
    assert source_limits + limits['max_total_tokens'] <= 6000000
    schema = dict(type='object', additionalProperties=False, required=['stage', 'review_status', 'verified_checks',
        'summary', 'uncovered', 'historical_basis', 'previous_stage_status', 'BC_benefit_proven'], properties=dict(
        stage=dict(type='string', enum=['S3_delivery_review']),
        review_status=dict(type='string', enum=['delivered', 'cannot_verify']),
        verified_checks=dict(type='integer', minimum=0, maximum=17), summary=dict(type='string'),
        uncovered=dict(type='array', items=dict(type='string')),
        historical_basis=dict(type='array', maxItems=3, items=dict(type='object', additionalProperties=False,
            required=['status', 'source_id', 'quote'], properties=dict(status=dict(type='string', enum=['source_cited', 'unknown']),
                source_id=dict(type='string'), quote=dict(type='string')))),
        previous_stage_status=dict(type='string', enum=['timed_out']), BC_benefit_proven=dict(type='boolean', enum=[False])))
    paths = [AREA / 'prepared.json', AREA / 'native-fixture-admission.json',
        AREA / 'isolated-S3-acceptance/result.json', AREA / 'isolated-S3-acceptance/registration.json',
        PRIOR / 'result.json', PRIOR / 'S3-supplemental/result.json', PRIOR / 'S3-graph-check/result.json', Path(__file__).resolve()]
    pins = {str(path): file_hash(path) for path in paths}
    pins.update({str(path): file_hash(path) for folder in ('src', 'experiments') for path in (ROOT / folder).rglob('*.py')})
    registration = dict(session=reg, limits=limits, envelope=envelope, prior_envelope=old_registration['envelope'],
        pins=pins, automatic_retries=0, whole_campaign_usage_complete=False,
        scope='Read-only delivery/recovery review of existing S3; no redevelopment, selection or reclassification of prior timeout')
    save(AREA / 'review-registration.json', registration)
    session = NativeForkSession(reg, AREA / 'review')
    budget = StudyBudget({'C/closeout': limits}, envelope['remaining_limits'])
    phases = []
    outcome = dict(scope=registration['scope'], whole_campaign_usage_complete=False, state='preflight')
    inference_started = False
    try:
        session.open()
        assert session.opened['sandbox']['type'] == 'readOnly'
        ticket, granted = budget.reserve('C/closeout', limits)
        evidence_paths = paths[:7]
        facts = dict(kind='source_bound_S3_review_observations', current_workspace=reg['workspace'],
            execution_mode='read_only', current_source_manifest=prepared['current_source_manifest'],
            independent_checks=dict(cumulative=11, concurrency=3, graph_and_keyboard=3, total=17),
            original_stage_completed=False, original_failure='registered_wall_cap',
            historical_usage_complete=False, BC_benefit_proven=False,
            evidence=[dict(path=str(path), sha256=file_hash(path)) for path in evidence_paths],
            isolated_fixture_root=reg['fixture_root'], phase_budget=granted,
            phase_deadline_utc=(datetime.now(timezone.utc) + timedelta(seconds=granted['max_seconds'])).isoformat())
        save(AREA / 'review-facts.json', facts)
        session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[
            dict(type='message', role='developer', content=[dict(type='input_text', text=json.dumps(facts, ensure_ascii=False))])]))
        request = ('请完成现有 S3 结果的只读交付核验。核验对象为当前源码和随附的既有独立回执。'
            '请说明已验证范围与未覆盖范围；最多列出三条影响这次 S3 实现的可见历史事实，给出原文短引及原始 source_id，依据不足则标为 unknown。'
            '本次交付范围是现有实现的核验说明。前一轮 600 秒中断的结果和未知用量保持原状态。输出简洁中文 JSON。')
        save(AREA / 'review-grant.json', dict(ticket=ticket, limits=granted, ledger=budget.snapshot()))
        def record(phase):
            phases.append(phase)
            save(AREA / 'review-phase.json', phase)
            settled = budget.settle(ticket, phase)
            save(AREA / 'review-settlement.json', dict(settlement=settled, ledger=budget.snapshot()))
        inference_started = True
        phase = session.execute_stage(request, AREA / 'review-phase', granted, record, output_schema=schema)
        outcome.update(state='completed' if phase['completed'] and phase['usage_complete'] and not phase['failure'] else 'incomplete',
            failure=phase['failure'], usage_complete=phase['usage_complete'])
        if outcome['state'] == 'completed':
            response = json.loads(phase['finals'][0]['text'])
            save(AREA / 'model-review.json', response)
            outcome['response'] = response
    except Exception as error:
        outcome.update(state='error', error=type(error).__name__ + ':' + str(error))
        if inference_started and not phases: budget.mark_unknown('C/closeout')
    finally:
        outcome['cleanup'] = session.close()
        if session.opened:
            closed = capture_rollout(session.opened['thread']['path'], archive=AREA / 'review-closed.jsonl')
            expected = {row['response_id']: row['usage'] for phase in phases for row in phase.get('receipts', {}).get('response_receipts', [])}
            actual = {row['payload']['response_id']: row['payload']['usage'] for row in closed.rows if row['type'] == 'token_usage_record'}
            late = [row for row in closed.rows if row['type'] == 'token_usage_record' and row['payload']['response_id'] not in expected]
            if any(actual.get(key) != value for key, value in expected.items()) or late or not closed.metadata['parse_complete']:
                budget.mark_unknown('C/closeout', usage(late, session.opened['thread']['id'])['response_receipts'] if late else ())
                outcome['state'] = 'accounting_unknown'
            outcome['closed_snapshot'] = closed.metadata
        outcome['source_unchanged'] = session.source_manifest() == reg['initial_manifest']
        outcome['pins_unchanged'] = all(file_hash(path) == value for path, value in pins.items())
        outcome['ledger'] = budget.snapshot()
        outcome['inference_started'] = inference_started
        response = outcome.get('response', {})
        outcome['read_only_closeout_passed'] = (outcome['state'] == 'completed' and outcome['source_unchanged']
            and outcome['pins_unchanged'] and outcome['cleanup']['empty_confirmed'] and not outcome['ledger']['study']['uncertain']
            and response.get('review_status') == 'delivered' and response.get('verified_checks') == 17)
        outcome['full_S2_to_S3_qualification_passed'] = False
        save(AREA / 'result.json', outcome)
    print({key: outcome.get(key) for key in ('state', 'failure', 'error', 'read_only_closeout_passed')}, flush=True)


if __name__ == '__main__':
    execute()
