"""Bounded first run of four prepared starters; preserve every expected gap."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'benchmarks/application-five-task-v1'
sys.path.insert(0, str(SUITE / 'acceptance'))
from runtime import manifest, save

OUT = Path('D:/agent-task-runs/wsc-four-app-starters-20261025-v1')
OUT.mkdir(exist_ok=False)
tasks = ['collaboration', 'files', 'imports', 'booking']


def check(task):
    folder = SUITE / 'tasks' / task
    contract = json.loads((folder / 'task.json').read_text(encoding='utf8'))
    assert len(contract['stages']) == 8 and contract['paired_repetitions'] == 3
    assert not contract['ready_to_launch']
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SUITE / 'acceptance/run.py'),
        task, str(folder / 'starter'), str(OUT / task)], capture_output=True, text=True,
        encoding='utf8', timeout=120)
    save(OUT / (task + '-process.json'), dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
    assert result.returncode == 0, result.stderr
    receipt = json.loads((OUT / task / 'result.json').read_text(encoding='utf8'))
    assert receipt['source_unchanged'] and not receipt['full_task_qualified']
    assert receipt['outcomes'][0]['id'] == 'startup_and_page' and receipt['outcomes'][0]['passed']
    assert receipt['passes'] == 1, 'new contract accidentally passes legacy starter'
    return dict(task=task, checks=receipt['checks'], passes=receipt['passes'],
                receipt=str(OUT / task / 'result.json'),
                receipt_sha256=sha256((OUT / task / 'result.json').read_bytes()).hexdigest())


with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(check, tasks))
save(OUT / 'review.json', dict(status='four_starters_boot_and_expected_gaps_observed',
     tasks=results, suite_manifest=manifest(SUITE), model_calls=0,
     positive_domain_calibration_complete=False, full_task_qualification=False))
print(json.dumps(results, ensure_ascii=False))
