"""Opt-in paired host routing and source-bound shared facts; no model planning."""
from pathlib import Path

from native_evidence import read, file_hash
from native_evaluation_host import MODE, attach, verify
from native_fixture_transport import MODE as TRANSPORT


def configure(registration, frozen, conditions):
    if not conditions.get('evaluation_host'):
        if conditions.get('shared_S2_evaluation_facts'):
            raise ValueError('paired_evaluation_host_missing')
        return registration
    if conditions['evaluation_host'] != MODE or conditions.get('fixture_transport') != TRANSPORT:
        raise ValueError('paired_evaluation_mode_unsupported')
    value = attach(registration, frozen)
    if conditions.get('shared_S2_evaluation_facts'):
        value['shared_S2_evaluation_facts'] = conditions['shared_S2_evaluation_facts']
        load_facts(value)
    return value


def grade_path(workspace, frozen, conditions, default):
    if not conditions.get('evaluation_host'):
        return default
    if conditions['evaluation_host'] != MODE or conditions.get('fixture_transport') != TRANSPORT:
        raise ValueError('paired_evaluation_mode_unsupported')
    return verify(Path(workspace) / '.wsc-runtime/evaluation-host-v1', frozen)


def public_binding(registration):
    if registration.get('evaluation_host') != MODE:
        raise ValueError('paired_evaluation_mode_unsupported')
    return dict(fixture_transport=TRANSPORT, evaluation_host=MODE,
        public_acceptance_harness=str(Path(registration['fixture_root']) / 'harness/run-acceptance.mjs'))


def load_facts(registration):
    reference = registration.get('shared_S2_evaluation_facts')
    if reference is None:
        return None
    if registration.get('evaluation_host') != MODE:
        raise ValueError('paired_evaluation_host_missing')
    if file_hash(reference['path']) != reference['sha256']:
        raise ValueError('paired_evaluation_facts_changed')
    value = read(reference['path'])
    if value.get('kind') != 'shared_S2_evaluation_facts_v2':
        raise ValueError('paired_evaluation_facts_kind_invalid')
    from native_evaluation_context import capture
    context = capture(Path(registration['workspace']) / 'gui', registration['fixture_root'],
        value['probe']['path'], entry='production_panel', scenario=value['visual']['scenario'],
        viewport=value['visual']['viewport'])
    if (context != value['execution_context'] or value['source_binding'] != context['gui']
            or file_hash(value['probe']['path']) != value['probe']['sha256']):
        raise ValueError('paired_evaluation_receiving_context_changed')
    # Cold facts are checked before inference, never silently treated as available.
    for receipt in (value['visual']['receipt'], value['component_baseline']['receipt']):
        if file_hash(receipt['path']) != receipt['sha256']:
            raise ValueError('paired_evaluation_receipt_changed')
    observed = read(value['visual']['receipt']['path'])
    if (observed['execution_context'] != context or observed['source_binding'] != context['gui']
            or any(observed[key] != value['visual'][key] for key in
                ('clipping_observed', 'real_wheel_changed_scroll', 'scenario', 'viewport'))):
        raise ValueError('paired_evaluation_visual_projection_changed')
    baseline = value['component_baseline']
    baseline_receipt = read(baseline['receipt']['path'])
    failed = sorted(case['fullName'] for suite in baseline_receipt['testResults']
        for case in suite.get('assertionResults', []) if case['status'] == 'failed')
    if (baseline_receipt['numPassedTests'] != baseline['passed']
            or baseline_receipt['numFailedTests'] != baseline['failed']
            or failed != sorted(baseline['failure_names'])):
        raise ValueError('paired_evaluation_baseline_projection_changed')
    for relative, expected in baseline['test_files'].items():
        if file_hash(Path(registration['workspace']) / 'gui' / relative) != expected:
            raise ValueError('paired_evaluation_baseline_tests_changed')
    return value


def as_event(value):
    from wsc.contracts import Event, encode, digest
    return Event('shared-evaluation-facts:' + digest(value), 'observation', value, text=encode(value))
