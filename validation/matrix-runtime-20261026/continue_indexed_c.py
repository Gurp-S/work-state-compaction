"""One registered C/S3 diagnostic, reusing the actual selected S2 checkpoint."""
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, digest, usage
from native_campaign_envelope import qualification_envelope
from native_application_budget import StudyBudget
from native_application_adapters import FrozenApplicationAdapters
from native_application_capability import admit
from native_study_fork_session import NativeForkSession
from native_rollout_snapshot import capture_rollout
from native_typed_content import dependencies
from wsc import WSC, Store
from wsc.publication import check_evidence
import native_cold_access

PRIOR = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')


def execute():
    OUT.mkdir(exist_ok=False)
    prior = read(PRIOR / 'registration.json')
    result = read(PRIOR / 'result.json')
    payload = read(PRIOR / 'staged/payload-C.json')
    replay = PRIOR / 'indexed-view-replay-v2'
    package = read(replay / 'package.json')
    assert digest({k: v for k, v in package.items() if k != 'package_digest'}) == package['package_digest']
    assert not result['ledger']['inflight']
    assert all(row['empty_confirmed'] for worker in result['outcomes'].values() for row in worker['cleanup'])
    assert read(PRIOR / 'indexed-native-import-v1/result.json')['package_sha256'] == file_hash(replay / 'package.json')
    # Chain the already-reduced historical envelope; withhold both old arm
    # allocations, including unused allowance. No old unknown ledger is resumed.
    envelope = qualification_envelope(result['ledger'], [], result['wall_seconds'])
    spent = result['ledger']['arms']['a3/sharedS2/C']
    assert not any(not phase['usage_complete'] for phase in result['outcomes']['C']['phases'])
    limits = dict(max_total_tokens=spent['limits']['max_total_tokens'] - spent['tokens'],
        max_responses=spent['limits']['max_responses'] - spent['responses'],
        max_seconds=spent['limits']['max_seconds'] - math.ceil(spent['seconds']))
    prefix = payload['common_prefix']
    reg = {**payload['registration'], 'parent_thread_id': prefix['reset_parent_thread_id'],
        'before_turn_id': prefix['reset_before_turn_id']}
    job = deepcopy(next(job for job in prior['jobs'] if job['arm'] == 'C'))
    job['resources']['output'] = str(OUT)
    pinned = [PRIOR / 'result.json', PRIOR / 'registration.json', PRIOR / 'staged/payload-C.json',
        Path(prefix['capsule']), replay / 'package.json',
        PRIOR / 'arms/C/output/S2-generation/model-draft.json', Path(__file__).resolve()]
    pins = {str(path): file_hash(path) for path in pinned}
    pins.update({str(p): file_hash(p) for folder in ('src', 'experiments') for p in (ROOT / folder).rglob('*.py')})
    registration = dict(created_at=datetime.now(timezone.utc).isoformat(), request=payload['stages'][2]['request'],
        session=reg, job=job, pins=pins, prior_envelope=prior['envelope'], envelope=envelope,
        arm_remaining_limits=limits, ordinary_seconds=600, inherited_C_known=dict(tokens=spent['tokens'], responses=spent['responses']),
        automatic_retries=0, whole_campaign_usage_complete=False,
        scope='C/S3 continuation diagnostic from archived choices; not a formal B/C pair or full application qualification')
    save(OUT / 'registration.json', registration)
    assert all(file_hash(path) == value for path, value in pins.items())
    # All package evidence is checked against an isolated copy of the replay
    # store. The historical failed C database is never written by this driver.
    source = sqlite3.connect('file:' + str(replay / 'wsc.db') + '?mode=ro', uri=True)
    target = sqlite3.connect(OUT / 'state.db')
    source.backup(target)
    source.close()
    target.close()
    core = WSC(Store(OUT / 'state.db', session_id='a3/sharedS2/C', workspace=reg['workspace']), access=lambda *args: True)
    check_evidence(core, package)
    arm = 'a3/S3-diagnostic/C'
    budget = StudyBudget({arm: limits}, envelope['remaining_limits'])
    session = NativeForkSession(reg, OUT / 'receiver')
    outcome = dict(scope=registration['scope'], state='preflight', whole_campaign_usage_complete=False)
    phases = []
    ticket = None
    inference_started = False
    try:
        session.open()
        quota = session.server.call('account/rateLimits/read', {})
        percentages = []
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'usedPercent': percentages.append(child)
                    else: collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(quota)
        save(OUT / 'quota-summary.json', dict(used_percentages=percentages, identifiers_omitted=True))
        if any(type(value) in (int, float) and value >= 100 for value in percentages):
            raise ValueError('provider_quota_exhausted_before_inference')
        admit(session, OUT / 'browser-capability')
        proof = session.inject(package['items'])
        save(OUT / 'checkpoint-import.json', proof)
        native_cold_access.package(session, package, OUT / 'cold-access', dependencies(core))
        runtime = dict(kind='native_execution_transition', current_workspace=reg['workspace'],
            inherited_context_source='shared_S2_indexed_checkpoint', allocated_local_ports=job['resources']['ports'],
            business_manifest_sha256=digest(reg['initial_manifest']))
        session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[
            dict(type='message', role='developer', content=[dict(type='input_text', text=__import__('json').dumps(runtime, ensure_ascii=False))])]))
        save(OUT / 'runtime-fact.json', runtime)
        ticket, granted = budget.reserve(arm, {**limits, 'max_seconds': 600})
        save(OUT / 'grant.json', dict(ticket=ticket, limits=granted, ledger=budget.snapshot()))
        def record(phase):
            phases.append(phase)
            save(OUT / 'phase-journal.json', phase)
            settlement = budget.settle(ticket, phase)
            save(OUT / 'settlement.json', dict(settlement=settlement, ledger=budget.snapshot()))
        print(dict(state='running_C_S3', limits=granted, repeated_selection=False), flush=True)
        inference_started = True
        phase = session.execute_stage(registration['request'], OUT / 'S3-phase', granted, record)
        outcome.update(state='native_completed' if phase['completed'] and not phase['failure'] and phase['usage_complete'] else 'native_incomplete',
            phase_completed=phase['completed'], failure=phase['failure'], usage_complete=phase['usage_complete'])
    except Exception as error:
        outcome.update(state='diagnostic_error', error=type(error).__name__ + ':' + str(error))
        if inference_started and not phases:
            budget.mark_unknown(arm)
    finally:
        outcome['cleanup'] = session.close()
        if session.opened:
            snap = capture_rollout(session.opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
            expected = {row['response_id']: row['usage'] for phase in phases for row in phase.get('receipts', {}).get('response_receipts', [])}
            actual = {row['payload']['response_id']: row['payload']['usage'] for row in snap.rows if row['type'] == 'token_usage_record'}
            changed = any(actual.get(key) != value for key, value in expected.items())
            late = [row for row in snap.rows if row['type'] == 'token_usage_record' and row['payload']['response_id'] not in expected]
            if changed or late or not snap.metadata['parse_complete']:
                budget.mark_unknown(arm, usage(late, session.opened['thread']['id'])['response_receipts'] if late else ())
                outcome.update(state='accounting_unknown', closed_receipts_changed=changed, late_receipts=len(late))
            outcome['closed_snapshot'] = snap.metadata
        outcome['ledger'] = budget.snapshot()
        outcome['inference_started'] = inference_started
        outcome['source_manifest_after'] = session.source_manifest()
        outcome['pins_unchanged'] = all(file_hash(path) == value for path, value in pins.items())
        save(OUT / 'native-result.json', outcome)
    if inference_started:
        adapters = FrozenApplicationAdapters(prior['conditions'], prior['tasks'], prior['expected_checks'], node_executable=prior['node_executable'])
        try:
            grade = adapters.grade(job, 3, OUT / 'S3-acceptance')
            save(OUT / 'S3-grade.json', grade)
            outcome['automatic_passed'] = all(row['passed'] for row in grade['observations'])
            outcome['automatic_checks'] = grade['observations']
        except Exception as error:
            outcome['grader_error'] = type(error).__name__ + ':' + str(error)
    outcome['C_S3_diagnostic_passed'] = (outcome['state'] == 'native_completed'
        and outcome.get('automatic_passed') is True and outcome['pins_unchanged']
        and outcome['cleanup']['empty_confirmed'] is True and not outcome['ledger']['study']['uncertain'])
    save(OUT / 'result.json', outcome)
    print({key: outcome.get(key) for key in ('state', 'failure', 'error', 'automatic_passed', 'C_S3_diagnostic_passed')}, flush=True)


if __name__ == '__main__':
    execute()
