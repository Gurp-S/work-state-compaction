"""Bounded author-only HTTP calibration. Usage: TASK ABS_NEW_OUTPUT FAULT..."""
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

task, raw_output, *faults = sys.argv[1:]
assert task in ('booking', 'files', 'collaboration') and faults and len(faults) == len(set(faults))
output = Path(raw_output)
assert output.is_absolute()
output.mkdir(exist_ok=False)
before = manifest(SUITE / 'tasks')
reference = (HERE / (task + '_service.py')).read_text(encoding='utf8')
assert reference.count("FAULT = 'none'") == 1


def run(fault):
    area = output / fault
    area.mkdir()
    workspace = area / 'workspace'
    shutil.copytree(SUITE / 'tasks' / task / 'starter', workspace)
    source = reference.replace("FAULT = 'none'", 'FAULT = ' + repr(fault), 1)
    (workspace / 'backend/service.py').write_text(source, encoding='utf8')
    process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SUITE / 'acceptance/run.py'),
        task, str(workspace), str(area / 'checks')], capture_output=True, text=True, encoding='utf8', timeout=120)
    save(area / 'process.json', dict(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr))
    assert process.returncode == 0, process.stderr
    result_path = area / 'checks/result.json'
    result = json.loads(result_path.read_text(encoding='utf8'))
    return dict(fault=fault, result=result, result_path=str(result_path), result_sha256=sha256(result_path.read_bytes()).hexdigest())


with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(run, faults))
assert manifest(SUITE / 'tasks') == before
save(output / 'raw-results.json', dict(task=task, runs=results, model_calls=0,
     production_tasks_unchanged=True, reference_sha256=sha256(reference.encode()).hexdigest(),
     note='Protocol calibration; author backend is outside task materials and has no complete UI'))
for item in results:
    result = item['result']
    print(json.dumps(dict(fault=item['fault'], checks=result['checks'], passes=result['passes'],
                         failed=[i['id'] for i in result['outcomes'] if not i['passed']]), ensure_ascii=False))
