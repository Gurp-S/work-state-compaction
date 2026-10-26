"""Settle completed calibration receipts; no grading or model execution."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, manifest, digest, file_hash
from native_public_checks import check_contract

area = Path('D:/agent-task-runs/wsc-public-contract-calibration-20261023-v1')
original = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
save(area / 'finalization-error.json', {
    'status': 'driver_assertion_failed_after_both_receipts_completed',
    'driver_sha256': file_hash(Path(__file__).with_name('calibrate.py')),
    'error': "AssertionError: calibration expected no unittest errors; actual parser ValueError is recorded as an error, not an assertion failure",
    'repair': 'Read-only settlement of existing complete receipts; no grader rerun or artifact edits'})
results, bindings, originals = {}, {}, {}
for arm in ('C', 'B'):
    workspace = area / arm / 'workspace'
    contract = read(workspace / 'task-contract/contract.json')
    binding = {'contract_sha256': digest(contract), 'protected_manifest': manifest(workspace / 'task-contract')}
    check_contract(workspace, binding)
    p = area / arm / 'acceptance/public-receipt.json'
    receipt = read(p)
    assert receipt['contract_sha256'] == binding['contract_sha256']
    assert receipt['source_manifest'] == manifest(workspace)
    assert receipt['executed_grader_sha256'] == contract['grader_sha256']
    assert file_hash(area / arm / 'acceptance/fixture/tests/_task_grader.py') == contract['grader_sha256']
    legacy_receipt = area / arm / 'acceptance/receipt.json'
    assert file_hash(legacy_receipt) == receipt['legacy_receipt_file_sha256']
    assert receipt['tests'] == 13 and not receipt['skipped']
    assert receipt['observed_runtime']['int_max_str_digits'] == 4300
    before = read(original / arm / 'line_budget_task/acceptance/receipt.json')['source_manifest']
    assert manifest(original / arm / 'final-workspace') == before
    originals[arm] = digest(before)
    bindings[arm] = binding
    results[arm] = {'tests': 13, 'passed': receipt['passed'], 'failures': receipt['failures'], 'errors': receipt['errors'],
                    'runtime': receipt['observed_runtime'], 'receipt_sha256': file_hash(p)}
assert bindings['C']['contract_sha256'] == bindings['B']['contract_sha256']
assert results['C']['runtime'] == results['B']['runtime']
assert results['B']['passed'] and not results['C']['passed']
assert not results['C']['failures'] and len(results['C']['errors']) == 4
assert all('test_large_signed_integer_value_and_hash' in e['test']
           and 'Exceeds the limit (4300 digits)' in e['trace'] for e in results['C']['errors'])
save(area / 'result.json', {'status': 'calibration_detected_known_contract_gap',
    'scope': 'Offline preserved-artifact copies, not new native task qualification', 'model_calls': 0,
    'original_task_artifacts_unchanged': True, 'bindings': bindings, 'results': results,
    'original_manifests_sha256': originals, 'grader_sha256': file_hash(area / 'contract-checks.py'),
    'driver_finalization_error_preserved': str(area / 'finalization-error.json'),
    'settlement_script_sha256': file_hash(__file__)})
print('settled: C known integer gap reproduced; B 13/13; original artifacts unchanged; no rerun')
