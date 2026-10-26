"""Review frozen components and evidence boundaries; no rerun of completed work."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest, digest

conditions = read(HERE / 'study-conditions-v1.json')
assert not conditions['launch_qualified'] and not conditions['paid_model_experiment_started']
assert conditions['boundaries']['after_stages'] == [2, 4, 6]
candidate = conditions['candidate']
assert file_hash(candidate['implementation']['path']) == candidate['implementation']['sha256']
assert manifest(ROOT / 'src') == candidate['core_manifest']
assert file_hash(conditions['executable']['path']) == conditions['executable']['sha256']
checks = read(HERE / 'checks.json')
for path, value in checks['source_pins'].items():
    if Path(path).name not in ('native_application_quality.py', 'test_native_application_limits_quality.py'):
        assert file_hash(path) == value
before = read(HERE / 'quality-registration-before.json')
after = read(HERE / 'quality-registration-after.json')
assert before['result']['status'] == 'passed' and after['result']['status'] == 'unknown'
assert before['source_sha256'] == file_hash(HERE / 'quality-before-registration-guard.py.txt')
assert after['source_sha256'] == file_hash(ROOT / 'experiments/native_application_quality.py')
save(HERE / 'final-check-scope.json', dict(candidate_methods=5, current_budget_quality_methods=9, total_distinct_methods=14,
    candidate_receipt=str(HERE / 'test_native_incremental_candidate-checks.json'),
    current_budget_quality_execution=dict(command='py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_native_application_limits_quality.py -v',
        observed_tool_chunk='20fad9', tests=9, passed=True,
        evidence_capture='Execution directly observed by current agent; original initial 13-method receipts retained'),
    current_quality_source_sha256=after['source_sha256'],
    current_quality_test_sha256=file_hash(ROOT / 'tests/test_native_application_limits_quality.py'),
    model_calls=0, native_boundary_or_model_selection_qualified=False))

a3_area = Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1')
a3 = read(a3_area / 'input-binding.json')
assert a3['production_source_unchanged'] and a3['model_calls'] == 0
assert manifest(Path(a3['workspace'])) == a3['source_manifest']
assert file_hash(a3['dependency_manifest']) == a3['dependency_manifest_sha256']
assert a3['dependency_files'] == 41935 and a3['dependency_bytes'] == 656671688
assert a3['copy_counts'] == {'reused': 41887, 'copied': 48}
runtime = read(a3_area / 'runtime.json')
assert not runtime['browser_launched'] and runtime['model_calls'] == 0
for record in (runtime['node'], runtime['chromium']):
    assert file_hash(record['executable']) == record['sha256']
baseline = Path('D:/agent-task-runs/wsc-a3-acceptance-20261023-v1/registration.json')
old = read(baseline)
assert old['source_manifest'] == {k.removeprefix('gui/src/'): h for k, h in a3['source_manifest'].items() if k.startswith('gui/src/')}
assert old['package_sha256'] == a3['source_manifest']['gui/package.json']
assert old['lock_sha256'] == a3['source_manifest']['gui/package-lock.json']
result = dict(status='candidate_policy_inputs_limits_quality_components_frozen_not_launch_qualified',
    conditions=dict(path=str(HERE / 'study-conditions-v1.json'), sha256=file_hash(HERE / 'study-conditions-v1.json')),
    candidate=candidate['id'], source_core_unchanged=True, offline_methods=14,
    A3=dict(binding=str(a3_area / 'input-binding.json'), binding_sha256=file_hash(a3_area / 'input-binding.json'),
        source_files=len(a3['source_manifest']), dependency_files=a3['dependency_files'], dependency_bytes=a3['dependency_bytes'],
        baseline_source_package_lock_match=True, original_baseline_registration_sha256=file_hash(baseline),
        browser_screenshots_repeated=False, dependency_copy_failures_retained=True),
    quality_old_registration_rebinding_reproduced_and_rejected=True, model_calls=0, paid_BC_started=False,
    remaining=['Actual native fork/import qualification for the declared three-boundary protocol',
               'Read-only generation client and its actual selection cost/response binding',
               'Connect cumulative grants, stage journals and task grader/quality adapters to matrix workers',
               'Per-arm A3 dependency materialization and external author-read audit'],
    limits=['Selection tests use synthetic draft callbacks, not demonstrated model retention or benefit',
            'Three exports were discarded after inspection, not reported as host installations',
            'Dependency verification is per-file sealed copying, not cross-file atomic filesystem proof',
            'Causal transport admission and model wire equivalence remain unproven'])
save(HERE / 'review.json', result)
print({k: result[k] for k in ('status', 'candidate', 'offline_methods', 'model_calls', 'paid_BC_started')})
