"""Seal source and bounded C/S3 evidence without copying dependencies/history."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')
WORK = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/arms/C/workspace')
BASE = ROOT / 'versions/20261025-shared-s2-indexed-checkpoint-v1-delta.zip'
TARGET = ROOT / 'versions/20261026-c-s3-diagnostic-and-fixture-transport-v1.zip'
outcome = read(AREA / 'result.json')
assert not outcome['ledger']['inflight'] and outcome['cleanup']['empty_confirmed']
assert outcome['C_S3_diagnostic_passed'] is False
assert read(AREA / 'S3-supplemental/result.json')['passed']
assert read(AREA / 'S3-graph-check/result.json')['passed']
assert read(AREA / 'fixture-transport-ab-v2/result.json')['reproduced_and_fixed']
files = {path.relative_to(ROOT).as_posix(): path for folder in ('src', 'experiments', 'tests')
    for path in (ROOT / folder).rglob('*.py')}
for path in Path(__file__).parent.iterdir():
    if path.is_file() and path.suffix in ('.py', '.mjs'):
        files[path.relative_to(ROOT).as_posix()] = path
for name in ('reviews/2026-10-26-c-s3-continuation.md', 'experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name] = ROOT / name
for path in AREA.rglob('*'):
    if path.is_file() and path.suffix in ('.json', '.mjs', '.tsx', '.html') and 'node_modules' not in path.parts:
        files['evidence/C-S3/' + path.relative_to(AREA).as_posix()] = path
for name in ('components/A3NativePanel.tsx', 'components/A3SnapshotPanel.tsx',
    'components/usage/DonutCard.tsx', 'components/usage/ModelTable.tsx', 'styles/a3-workspace.css'):
    files['application-delta/gui/src/' + name] = WORK / 'gui/src' / name
for path in (WORK / 'validation').glob('a3-s3-interaction-20261026-*/*.json'):
    files['evidence/model-own/' + path.relative_to(WORK / 'validation').as_posix()] = path
files['evidence/model-own/a3-s3-interaction.mjs'] = WORK / 'validation/a3-s3-interaction.mjs'
artifacts = {str(path): file_hash(path) for path in AREA.rglob('*.png') if 'node_modules' not in path.parts}
index = dict(format='c_s3_diagnostic_and_isolated_fixture_transport_v1',
    base=str(BASE), base_sha256=file_hash(BASE), files={name: file_hash(path) for name, path in files.items()},
    screenshot_receipts=artifacts, current_scope='Current opt-in transport source; closed failed C/S3 execution and 17 independent passing feature checks',
    original_run_pins_unchanged=outcome['pins_unchanged'], whole_campaign_usage_complete=False,
    original_C_diagnostic_passed=False, excluded=['dependencies', 'raw native histories', 'screenshot duplicate bytes', 'database duplicate bytes'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items(): archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=file_hash(TARGET), bytes=TARGET.stat().st_size,
    source_files=sum(name.startswith(('src/', 'experiments/', 'tests/')) for name in files),
    files=len(files), screenshots_referenced=len(artifacts), base_sha256=index['base_sha256'], scope=index['current_scope'])
save(Path(__file__).parent / 'delivery.json', receipt)
print(receipt)
