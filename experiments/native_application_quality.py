"""Evidence-bound quality settlement; automatic checks never imply UI completion."""
from pathlib import Path

from native_evidence import digest, file_hash, read


def settle_quality(binding, current_source_manifest, expected_check_ids, manual_requirements, *, current_auxiliary=None):
    """binding comes from the external grader adapter, not a model self-report.

    The adapter pins result/registration/individual receipt files and maps the
    task's source scope. This validator refuses incomplete, stale or unbound
    evidence; it does not execute or trust an arbitrary submitted grader.
    """
    unknown = lambda reason: dict(status='unknown', reason=reason, evidence_sha256=digest(binding))
    if not expected_check_ids or not manual_requirements:
        return unknown('quality_registered_requirements_missing')
    files = binding.get('files', {})
    if not files or not all(Path(path).is_file() and file_hash(path) == value for path, value in files.items()):
        return unknown('quality_evidence_missing_or_changed')
    if binding.get('source_manifest') != current_source_manifest or binding.get('auxiliary', {}) != (current_auxiliary or {}):
        return unknown('quality_source_or_auxiliary_changed')
    kind = binding.get('kind')
    registration_path, result_path = binding.get('registration_path'), binding.get('result_path')
    if kind not in {'a3', 'http'} or registration_path not in files or result_path not in files:
        return unknown('quality_registration_or_result_unbound')
    root = Path(result_path).resolve().parent
    if Path(registration_path).resolve() != root / 'registration.json' or Path(result_path).name != 'result.json':
        return unknown('quality_registration_result_run_mismatch')
    registration, result = read(registration_path), read(result_path)
    if registration.get('source_manifest') != current_source_manifest or any(
            registration.get(key) != value for key, value in (current_auxiliary or {}).items()):
        return unknown('quality_recorded_registration_source_changed')
    grader = registration.get('harness_manifest' if kind == 'a3' else 'acceptance_manifest')
    if not grader or grader != binding.get('grader_manifest'):
        return unknown('quality_registered_grader_changed')
    if kind == 'a3':
        if result.get('status') != 'completed_checks' or result.get('stage') != 'S8' or result.get('mutation') != 'none' or result.get('selected_subset') is not False:
            return unknown('quality_full_a3_run_missing')
    elif result.get('status') != 'completed_public_http_checks' or result.get('stage') != 8 or result.get('source_unchanged') is not True:
        return unknown('quality_full_http_run_missing')
    automatic = binding.get('automatic', [])
    observed_ids = [row.get('id') for row in automatic]
    if set(observed_ids) != set(expected_check_ids) or len(observed_ids) != len(set(observed_ids)):
        return unknown('quality_automatic_coverage_incomplete')
    if not all(type(row.get('passed')) is bool and row.get('receipt') in files for row in automatic):
        return unknown('quality_automatic_evidence_unbound')
    for row in automatic:
        expected_path = root / (row['id'] + '.json') if kind == 'a3' else root / row['id'] / 'receipt.json'
        if Path(row['receipt']).resolve() != expected_path:
            return unknown('quality_check_receipt_from_different_run')
        receipt = read(row['receipt'])
        if receipt.get('id') != row['id'] or receipt.get('passed') is not row['passed']:
            return unknown('quality_automatic_receipt_mismatch')
    outcomes = result.get('outcomes', [])
    if len(outcomes) != len(automatic) or {row.get('id'): row.get('passed') for row in outcomes} != {
            row['id']: row['passed'] for row in automatic}:
        return unknown('quality_result_outcomes_mismatch')
    if any(not row['passed'] for row in automatic):
        return dict(status='failed', reason='registered_automatic_check_failed', evidence_sha256=digest(binding))
    manual = binding.get('manual', [])
    if len(manual) != len({row.get('id') for row in manual}) or set(row.get('id') for row in manual) != set(manual_requirements):
        return unknown('quality_manual_coverage_incomplete')
    for row in manual:
        if row.get('status') not in {'pass', 'fail'} or not row.get('evidence') or not all(path in files for path in row['evidence']):
            return unknown('quality_manual_evidence_missing')
    if any(row['status'] == 'fail' for row in manual):
        return dict(status='failed', reason='registered_manual_check_failed', evidence_sha256=digest(binding))
    return dict(status='passed', reason='registered_automatic_and_manual_requirements_passed', evidence_sha256=digest(binding))
