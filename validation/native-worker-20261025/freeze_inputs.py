"""Freeze only the four prepared applications; no model calls or tests repeated."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_inputs import TASKS, freeze_task
from native_evidence import save, manifest, file_hash

AREA = Path('D:/agent-task-runs/wsc-four-app-inputs-20261025-v1')
AREA.mkdir()
source = ROOT / 'benchmarks/application-five-task-v1'
before = manifest(source)
records = []
for task in TASKS:
    record = freeze_task(source, task, AREA / task)
    names = record['source_manifest']
    assert all(not any(part in name.split('/') for part in ('calibration', 'validation', 'versions')) for name in names)
    assert not any(name.endswith('_service.py') for name in names)
    assert 'backend/service.py' in names
    assert not any(other != task and f'/tasks/{other}/' in name for other in TASKS for name in names)
    records.append(dict(task=task, binding=str(AREA / task / 'input-binding.json'),
        binding_sha256=file_hash(AREA / task / 'input-binding.json'), source_manifest_sha256=record['source_manifest_sha256'],
        files=len(names)))
assert manifest(source) == before
save(AREA / 'result.json', dict(status='four_inputs_frozen_not_launch_qualified', tasks=records,
    model_calls=0, original_source_unchanged=True, read_isolation_proven=False,
    A3_frozen=False, note='External author files not copied; no claim about external read denial'))
print(json.dumps(records))
