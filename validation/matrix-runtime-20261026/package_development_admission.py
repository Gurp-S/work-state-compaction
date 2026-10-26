"""Preserve both closed development trials and the unproven scoped-state repair."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, file_hash, save

BASE = ROOT / 'versions/20261026-capsule-model-delivery-v1-delta.zip'
TARGET = ROOT / 'versions/20261026-real-development-time-policy-and-scoped-state-v1-delta.zip'
AREAS = [Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1'), Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')]
source = {path.relative_to(ROOT).as_posix(): path for folder in ('src', 'experiments', 'tests')
    for path in (ROOT / folder).rglob('*.py')}
files = dict(source)
for path in Path(__file__).parent.iterdir():
    if path.is_file() and path.suffix in ('.py', '.mjs', '.txt'):
        files[path.relative_to(ROOT).as_posix()] = path
for name in ('reviews/2026-10-26-real-development-admission.md', 'experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name] = ROOT / name
screenshots = {}
template = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace')
for area in AREAS:
    outcome = read(area / 'result.json')
    assert not outcome['ledger']['inflight'] and outcome['cleanup']['empty_confirmed']
    assert not outcome['native_and_cumulative_checks_passed']
    for path in area.rglob('*.json'):
        relative = path.relative_to(area)
        if not any(part in ('workspace', 'cold-public', 'cold-objects') for part in relative.parts):
            files['evidence/' + area.name + '/' + relative.as_posix()] = path
    for path in (area / 'workspace/gui/src').rglob('*'):
        if path.is_file():
            relative = path.relative_to(area / 'workspace')
            old = template / relative
            if not old.exists() or file_hash(path) != file_hash(old):
                files['application-delta/' + area.name + '/' + relative.as_posix()] = path
    for folder in ('S3-acceptance', 'S3-supplemental', 'S3-scope-check-v2'):
        for path in (area / folder).glob('*.png'):
            screenshots[str(path)] = file_hash(path)
old = read(AREAS[0] / 'registration.json')
backup = ROOT / 'validation/matrix-runtime-20261026/run-dev-before-shared-time.py.txt'
assert file_hash(backup) == old['pins'][str(ROOT / 'validation/matrix-runtime-20261026/run_dev_trial.py')]
new = read(AREAS[1] / 'registration.json')
assert file_hash(ROOT / 'validation/matrix-runtime-20261026/run_dev_trial.py') == new['pins'][str(ROOT / 'validation/matrix-runtime-20261026/run_dev_trial.py')]
index = dict(format='real_development_time_policy_and_scoped_state_v1', base=str(BASE), base_sha256=file_hash(BASE),
    source_manifest={name: file_hash(path) for name, path in source.items()},
    files={name: file_hash(path) for name, path in files.items()}, screenshot_receipts=screenshots,
    original_executed_600s_driver_hash_verified=True, shared_time_executed_driver_hash_verified=True,
    scope='Two failed real development admissions; 17 functional checks in shared-time trial; offline scoped-state repair only',
    formal_BC_pairs_started=0, whole_campaign_usage_complete=False,
    excluded=['dependencies', 'browser binaries', 'raw native histories', 'database copies', 'screenshot duplicate bytes'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items(): archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=file_hash(TARGET), bytes=TARGET.stat().st_size,
    source_files=len(source), files=len(files), scope=index['scope'])
save(Path(__file__).parent / 'development-admission-delivery.json', receipt)
print(receipt)
