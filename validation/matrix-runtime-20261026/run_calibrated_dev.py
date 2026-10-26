"""One reviewed incremental-package C development; historical ledgers remain frozen."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, digest, usage
from native_campaign_envelope import qualification_envelope
from native_application_budget import StudyBudget
from native_study_fork_session import NativeForkSession
from native_application_capability import admit
from native_application_adapters import FrozenApplicationAdapters
from native_fixture_transport import public_binding
from native_typed_content import dependencies
from native_rollout_snapshot import capture_rollout
from wsc import WSC, Store
from wsc.publication import check_evidence
import native_cold_access

OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1')
COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')


def execute(*, OUT=OUT, ordinary_time_shared=True, budget_parent=None):
    OUT = Path(OUT)
    prepared = read(OUT / 'prepared.json')
    parent = Path(budget_parent or PRIOR)
    prior = read(parent / 'result.json')
    oldreg = read(parent / 'registration.json')
    assert not prior['ledger']['inflight'] and prior['cleanup']['empty_confirmed']
    elapsed = (parent / 'result.json').stat().st_mtime - (parent / 'registration.json').stat().st_mtime
    envelope = read(parent / 'next-admission-envelope.json')
    import time, math
    envelope = deepcopy(envelope)
    elapsed_since_seal = time.time() - (parent / 'next-admission-envelope.json').stat().st_mtime
    assert elapsed_since_seal >= 0
    envelope['remaining_limits']['max_seconds'] -= math.ceil(elapsed_since_seal)
    assert envelope['remaining_limits']['max_seconds'] >= 2700
    envelope['whole_campaign_usage_complete'] = False
    source_reg = read(COMMON / 'registration.json')
    conditions = {**deepcopy(source_reg['conditions']), 'fixture_transport': 'http_attached_websocket_v1',
        'indexed_checkpoint': True, 'phase_budget_facts': True, 'standalone_stage': 3,
        'evaluation_host': 'a3_production_panel_host_v1'}
    if ordinary_time_shared:
        from native_stage_time_policy import propose
        conditions = propose(conditions)
    limits = dict(conditions['budgets']['per_arm'])
    phase_limits = dict(conditions['budgets']['ordinary_phase'])
    reg = prepared['registration']
    package = read(prepared['package'])
    assert file_hash(prepared['package']) == prepared['package_sha256']
    core = WSC(Store(OUT / 'state.db', session_id='a3/calibrated-selection-v1/C', workspace=reg['workspace']), access=lambda *args: True)
    check_evidence(core, package)
    pins = {str(path): file_hash(path) for path in [OUT / 'prepared.json', Path(prepared['package']),
        Path(prepared['original_draft']), Path(prepared['source_review']), OUT/'verification-plan.json', parent/'next-admission-envelope.json', parent / 'result.json', parent / 'registration.json', Path(__file__).resolve()]}
    pins.update({str(path): file_hash(path) for folder in ('src', 'experiments') for path in (ROOT / folder).rglob('*.py')})
    if ordinary_time_shared:
        adoption = read(OUT / 'policy-adoption.json')
        assert adoption['ordinary_time_seconds'] == conditions['budgets']['ordinary_phase']['max_seconds']
        pins[str(OUT / 'policy-adoption.json')] = file_hash(OUT / 'policy-adoption.json')
    registration = dict(created_at=datetime.now(timezone.utc).isoformat(), conditions=conditions,
        session=reg, envelope=envelope, previous_registration=str(parent / 'registration.json'),
        arm_limits=limits, phase_limits=phase_limits, pins=pins, request=prepared['request'],
        original_selection_generation_charged_once_in_history=True, automatic_retries=0,
        whole_campaign_usage_complete=False,
        scope='Calibrated-package actual S2->S3 continuation, original task/caps, explicit host and baseline evidence; not formal B/C')
    save(OUT / 'registration.json', registration)
    arm = 'a3/' + OUT.name + '/C'
    budget = StudyBudget({arm: limits}, envelope['remaining_limits'])
    session = NativeForkSession(reg, OUT / 'receiver')
    phases = []
    outcome = dict(state='preflight', scope=registration['scope'], whole_campaign_usage_complete=False)
    inference_started = False
    try:
        session.open()
        admit(session, OUT / 'browser-capability')
        session.inject(package['items'])
        native_cold_access.package(session, package, OUT / 'cold-access', dependencies(core))
        ticket, granted = budget.reserve(arm, phase_limits)
        facts = dict(kind='native_development_execution_state', stage='S3', current_workspace=reg['workspace'],
            business_manifest_sha256=digest(reg['initial_manifest']),
            phase_budget=granted, phase_deadline_utc=(datetime.now(timezone.utc)+timedelta(seconds=granted['max_seconds'])).isoformat(),
            allocated_local_ports=[29520, 29521, 29522],
            public_acceptance_helper_module=str(Path(reg['fixture_root'])/'harness/acceptance-cases.mjs'),
            **public_binding(reg))
        save(OUT / 'runtime-facts.json', facts)
        session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[
            dict(type='message', role='developer', content=[dict(type='input_text', text=json.dumps(facts, ensure_ascii=False))])]))
        save(OUT / 'grant.json', dict(ticket=ticket, limits=granted, ledger=budget.snapshot()))
        def record(phase):
            phases.append(phase)
            save(OUT / 'phase-journal.json', phase)
            settled = budget.settle(ticket, phase)
            save(OUT / 'settlement.json', dict(settlement=settled, ledger=budget.snapshot()))
        print(dict(state='running_real_S3', limits=granted, selection_regenerated=False), flush=True)
        inference_started = True
        phase = session.execute_stage(prepared['request'], OUT / 'S3-phase', granted, record)
        outcome.update(state='native_completed' if phase['completed'] and phase['usage_complete'] and not phase['failure'] else 'native_incomplete',
            failure=phase['failure'], usage_complete=phase['usage_complete'])
    except Exception as error:
        outcome.update(state='error', error=type(error).__name__+':'+str(error))
        if inference_started and not phases: budget.mark_unknown(arm)
    finally:
        outcome['cleanup'] = session.close()
        if session.opened:
            snap = capture_rollout(session.opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
            expected = {row['response_id']: row['usage'] for phase in phases for row in phase.get('receipts',{}).get('response_receipts',[])}
            actual = {row['payload']['response_id']: row['payload']['usage'] for row in snap.rows if row['type']=='token_usage_record'}
            late = [row for row in snap.rows if row['type']=='token_usage_record' and row['payload']['response_id'] not in expected]
            if any(actual.get(key)!=value for key,value in expected.items()) or late or not snap.metadata['parse_complete']:
                budget.mark_unknown(arm, usage(late,session.opened['thread']['id'])['response_receipts'] if late else ())
                outcome['state']='accounting_unknown'
            outcome['closed_snapshot']=snap.metadata
        outcome['ledger']=budget.snapshot()
        outcome['inference_started']=inference_started
        outcome['source_manifest_after']=session.source_manifest()
        outcome['pins_unchanged']=all(file_hash(path)==value for path,value in pins.items())
        save(OUT / 'native-result.json', outcome)
    if inference_started:
        job = deepcopy(next(job for job in source_reg['jobs'] if job['arm']=='C'))
        job['resources'].update(workspace=reg['workspace'],output=str(OUT))
        adapter = FrozenApplicationAdapters(conditions,source_reg['tasks'],source_reg['expected_checks'],node_executable=source_reg['node_executable'])
        try:
            grade=adapter.grade(job,3,OUT/'S3-acceptance')
            outcome['automatic_checks']=grade['observations']
            outcome['automatic_passed']=all(row['passed'] for row in grade['observations'])
            save(OUT/'S3-grade.json',grade)
        except Exception as error: outcome['grader_error']=type(error).__name__+':'+str(error)
    outcome['native_and_cumulative_checks_passed']=(outcome['state']=='native_completed' and outcome.get('automatic_passed') is True
        and outcome['pins_unchanged'] and outcome['cleanup']['empty_confirmed'] and not outcome['ledger']['study']['uncertain'])
    outcome['full_S3_requirement_review']='pending_supplemental_and_manual_review'
    save(OUT/'result.json',outcome)
    print({key:outcome.get(key) for key in ('state','failure','error','automatic_passed','native_and_cumulative_checks_passed')},flush=True)


if __name__ == '__main__': execute()
