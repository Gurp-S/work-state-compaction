"""Offline checks and retained real-record replay; never starts a model."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'tests')]
from native_evidence import digest, file_hash, read, save
from native_fork_phase import account_fork_turn
from native_turn_accounting import account_turn

OUT = Path(__file__).parent
AREA = Path('D:/agent-task-runs/wsc-fork-admission-20261023-v1/single-response-probe')
patterns = ('test_fork_phase.py', 'test_native_turn_accounting.py',
            'test_native_execution_binding.py', 'test_native_phase_budget.py', 'test_fork_history.py')
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
          for p in sorted((ROOT / folder).rglob('*.py'))}
suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=p)
                           for p in patterns)
log = StringIO()
with redirect_stdout(log), redirect_stderr(log):
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
log_path = OUT / 'checks.log'
with log_path.open('x', encoding='utf8') as stream:
    stream.write(log.getvalue())
assert source == {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
                  for p in sorted((ROOT / folder).rglob('*.py'))}
before, after = (AREA / 'before.jsonl').read_bytes(), (AREA / 'after.jsonl').read_bytes()
binding, original = read(AREA / 'history-binding.json'), read(AREA / 'result.json')
args = {'thread_id': original['receipts']['thread_id'], 'turn_id': original['turn_id']}
old = account_turn(before, after, **args)
new = account_fork_turn(before, after, binding=binding, **args)
assert not old['complete'] and new['complete'], (old['reasons'], new['reasons'])
assert new['receipts'] == original['receipts']
assert new['known_usage']['total_tokens'] == 26955
assert new['inherited_thread_counter']['total_tokens'] == 576406
assert new['display_counter_baseline']['total_tokens'] == 526494
receipt = {'scope': 'Fork admission, incremental accounting, directly affected execution and budget checks; not full suite or model quality',
    'source_manifest': source, 'source_manifest_sha256': digest(source),
    'tests': result.testsRun, 'passed': result.wasSuccessful(), 'patterns': patterns,
    'log_sha256': file_hash(log_path), 'real_replay': {
        'old_complete': old['complete'], 'old_reasons': old['reasons'], 'new_complete': new['complete'],
        'known_usage': new['known_usage'], 'response_count': new['receipts']['response_count'],
        'parent_thread_total': new['inherited_thread_counter']['total_tokens'],
        'parent_display_total': new['display_counter_baseline']['total_tokens'],
        'before_sha256': file_hash(AREA / 'before.jsonl'), 'after_sha256': file_hash(AREA / 'after.jsonl'),
        'registration_sha256': file_hash(AREA / 'registration.json'),
        'original_result_sha256': file_hash(AREA / 'result.json'),
        'history_binding_sha256': file_hash(AREA / 'history-binding.json')},
    'new_model_calls_in_validation': 0,
    'preceding_protocol_probe_model_calls': 1,
    'paid_probe_used_shared_phase': False}
save(OUT / 'checks.json', receipt)
print(json.dumps({'tests': result.testsRun, 'passed': result.wasSuccessful(),
                  'sources': len(source), 'real_replay': receipt['real_replay']}, ensure_ascii=False))
if not result.wasSuccessful():
    print(log.getvalue())
    raise SystemExit(1)
