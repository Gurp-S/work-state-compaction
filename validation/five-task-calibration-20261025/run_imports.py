"""Run author-only positive and explicit fault calibration over actual HTTP."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'benchmarks/application-five-task-v1'
HERE = Path(__file__).parent
sys.path.insert(0, str(SUITE / 'acceptance'))
from runtime import save, manifest

OUT = Path('D:/agent-task-runs/wsc-imports-positive-calibration-20261025-v1')
OUT.mkdir(exist_ok=False)
before = manifest(SUITE / 'tasks')
reference = (HERE / 'imports_service.py').read_text(encoding='utf8')
assert reference.count("FAULT = 'none'") == 1
names = ['none', 'unknown_as_zero', 'duplicate_commit', 'replacement_decode']


def execute(name):
    area = OUT / name
    area.mkdir()
    workspace = area / 'workspace'
    shutil.copytree(SUITE / 'tasks/imports/starter', workspace)
    source = reference.replace("FAULT = 'none'", 'FAULT = ' + repr(name), 1)
    (workspace / 'backend/service.py').write_text(source, encoding='utf8')
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SUITE / 'acceptance/run.py'),
        'imports', str(workspace), str(area / 'checks')], capture_output=True, text=True,
        encoding='utf8', timeout=90)
    save(area / 'process.json', dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
    assert result.returncode == 0, result.stderr
    outcome = json.loads((area / 'checks/result.json').read_text(encoding='utf8'))
    return dict(fault=name, result=outcome, result_path=str(area / 'checks/result.json'),
                result_sha256=sha256((area / 'checks/result.json').read_bytes()).hexdigest())


with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(execute, names))
assert manifest(SUITE / 'tasks') == before
save(OUT / 'raw-results.json', dict(runs=results, model_calls=0, production_tasks_unchanged=True,
    reference_sha256=sha256(reference.encode()).hexdigest(),
    note='Author backend has no complete UI; calibration is not model or full application evidence'))
for result in results:
    outcome = result['result']
    print(json.dumps(dict(fault=result['fault'], checks=outcome['checks'], passes=outcome['passes'],
                         failed=[r['id'] for r in outcome['outcomes'] if not r['passed']]), ensure_ascii=False))
