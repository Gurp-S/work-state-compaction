"""Capture narrowly scoped candidate, budget and quality checks with source pins."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import file_hash, save

checks = []
for name, expected in [('test_native_incremental_candidate.py', 5), ('test_native_application_limits_quality.py', 8)]:
    process = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'unittest', 'discover',
        '-s', str(ROOT / 'tests'), '-p', name, '-v'], capture_output=True, text=True, encoding='utf8')
    record = dict(test_file=name, expected_methods=expected, returncode=process.returncode,
                  stdout=process.stdout, stderr=process.stderr)
    save(HERE / (name.removesuffix('.py') + '-checks.json'), record)
    checks.append(record)
assert all(c['returncode'] == 0 and f"Ran {c['expected_methods']} tests" in c['stderr'] for c in checks)
pins = {str(ROOT / folder / name): file_hash(ROOT / folder / name) for folder, name in [
    ('experiments', 'native_incremental_candidate.py'), ('experiments', 'native_application_budget.py'),
    ('experiments', 'native_application_quality.py'), ('tests', 'test_native_incremental_candidate.py'),
    ('tests', 'test_native_application_limits_quality.py')]}
save(HERE / 'checks.json', dict(passed=True, methods=13, source_pins=pins, model_calls=0,
    initial_check_correction='The first parallel-reservation fixture reserved all 10 study response slots; corrected study response budget to 20. This was not a budget implementation failure.',
    scope='Synthetic semantic-selection callbacks, budget and quality settlement; not actual model compression or native installation'))
print(json.dumps(dict(methods=13, passed=True, model_calls=0)))
