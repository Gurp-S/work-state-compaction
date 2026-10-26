"""Settle completed native repeats and manual artifact review without rerunning."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, digest, manifest
from run_native_pair import verify_pins

AREA = Path('D:/agent-task-runs/wsc-native-repeat-20261023-v1')
reg, result = read(AREA / 'registration.json'), read(AREA / 'result.json')
assert result['status'] == 'two_native_repeats_executed_review_pending'
assert result['archive_usage_verified'] and result['usage']['complete']
assert result['source_live_unchanged'] and result['original_workspace_unchanged']
verify_pins(reg)
rows = {}
for name in ('N1', 'N2'):
    workspace = AREA / reg['archive_slots'][name] / 'final-workspace'
    receipt = read(AREA / name / 'acceptance/receipt.json')
    phase = read(AREA / name / 'phase-outcome.json')
    assert receipt['passed'] and receipt['tests'] == 10 and receipt['names'] == reg['methods']
    assert manifest(workspace) == receipt['source_manifest']
    assert phase['usage_complete'] and phase['completed'] and phase['failure'] is None
    assert 'accounting_error' not in result['threads'][name]
    assert result['threads'][name]['rollout_snapshot']['parse_complete']
    assert file_hash(AREA / name / 'rollout.jsonl') == phase['rollout_sha256']
    events = [json.loads(line) for line in (AREA / name / 'events.jsonl').read_text(encoding='utf8').splitlines()]
    commands = [r['params']['item'] for r in events if r.get('method') == 'item/completed'
                and r.get('params', {}).get('item', {}).get('type') == 'commandExecution']
    assert any('Ran 10 tests' in (i.get('aggregatedOutput') or '')
               and 'OK' in (i.get('aggregatedOutput') or '') and i.get('exitCode') == 0 for i in commands)
    u = phase['receipts']['all_usage']
    rows[name] = {'seconds': phase['seconds'], 'responses': phase['receipts']['response_count'],
        **u, 'uncached_input_tokens': u['input_tokens'] - u['cached_input_tokens'],
        'output_minus_reported_reasoning': u['output_tokens'] - u['reasoning_output_tokens'],
        'command_count': len(commands), 'acceptance': '10/10',
        'artifact_manifest_sha256': digest(manifest(workspace)),
        'strict_parser_sha256': file_hash(workspace / 'src/wsc/strict_jsonl.py'),
        'phase_sha256': file_hash(AREA / name / 'phase-outcome.json'),
        'acceptance_sha256': file_hash(AREA / name / 'acceptance/receipt.json'),
        'events_sha256': file_hash(AREA / name / 'events.jsonl')}
    if name == 'N2':
        save(AREA / name / 'semantic-review.json', {
            'status': 'qualified_for_registered_finite_continuation',
            'scope': 'One native repeat with ten public finite-stage methods, no line budget or full WSC claim',
            'binding': {k: rows[name][k] for k in ('artifact_manifest_sha256', 'phase_sha256', 'acceptance_sha256')},
            'code_review': ['Nine-digit chunk integer construction preserves signed arbitrary precision without global digit-limit mutation',
                'parse_float rejects nonfinite results; parse_constant rejects all nonstandard constants',
                'Dedicated internal exception is translated before malformed-tail fallback; original duplicate-key, physical line and hash behavior retained',
                'Only registered sidecar changed; existing protected files and public acceptance contract retained'],
            'final_report_review': ['Ten-method pass matches actual model check and external manifest-bound receipt',
                'Unchanged default reader hash and exclusion of line-byte budget match preserved artifacts'],
            'trajectory_review': ['Five-method pre-edit failure is a deliberate baseline, not a failed delivered version',
                'One memory-search regular expression failed; no evidence makes this WSC-specific'],
            'parent_artifact_edits': False, 'additional_model_calls': 0})
    assert read(AREA / name / 'semantic-review.json')['status'] == 'qualified_for_registered_finite_continuation'
numeric = ('seconds', 'responses', 'input_tokens', 'cached_input_tokens', 'uncached_input_tokens',
           'output_tokens', 'reasoning_output_tokens', 'output_minus_reported_reasoning', 'total_tokens', 'command_count')
percent = {k: (rows['N2'][k] / rows['N1'][k] - 1) * 100 for k in numeric}
review = {'status': 'two_native_repeats_qualified_for_registered_finite_stage',
    'registration_sha256': file_hash(AREA / 'registration.json'), 'result_sha256': file_hash(AREA / 'result.json'),
    'paired_admission_sha256': file_hash(AREA / 'paired-admission.json'),
    'rows': rows, 'N2_vs_N1_percent': percent, 'new_usage': result['usage'],
    'historical_parent_thread_counter_total': 576406,
    'historical_parent_cost_is_not_new_spend': True,
    'interpretation': ['Same saved native history and visible configuration can produce different action paths and costs',
        'Two observations do not estimate the sampling distribution or isolate temperature',
        'No non-native transport contrast was run and no WSC improvement is established',
        'Original B/C results are not pooled with this new public-contract and relocated-cwd study'],
    'source_and_original_workspace_unchanged': True, 'cash': None, 'goal_complete': False,
    'parent_review_model_calls': 0}
save(AREA / 'reviewed-result.json', review)
save(Path(__file__).parent / 'result-pointer.json', {'path': str(AREA / 'reviewed-result.json'),
    'sha256': file_hash(AREA / 'reviewed-result.json'), 'review_script_sha256': file_hash(__file__),
    'new_model_responses': result['usage']['response_count'],
    'new_total_tokens': result['usage']['complete_usage']['total_tokens'], 'goal_complete': False})
print(json.dumps({'status': review['status'], 'N2_vs_N1_percent': percent,
                  'responses': result['usage']['response_count'], 'tokens': result['usage']['complete_usage']['total_tokens']}, ensure_ascii=False))
