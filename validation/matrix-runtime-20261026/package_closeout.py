"""Small immutable revision for fixture integration and review admission repair."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
BASE = ROOT / 'versions/20261026-c-s3-diagnostic-and-fixture-transport-v1.zip'
TARGET = ROOT / 'versions/20261026-review-fixture-integration-and-capsule-v1-delta.zip'
result = read(AREA / 'result.json')
assert result['cleanup']['empty_confirmed'] and not result['ledger']['inflight']
assert not result['read_only_closeout_passed']
assert read(AREA / 'capsule-receiver-admission-v2/result.json')['passed']
source = {path.relative_to(ROOT).as_posix(): path for folder in ('src', 'experiments', 'tests')
    for path in (ROOT / folder).rglob('*.py')}
current = {**source, **{path.relative_to(ROOT).as_posix(): path for path in Path(__file__).parent.iterdir()
    if path.is_file() and path.suffix in ('.py', '.mjs')}}
files = {}
with zipfile.ZipFile(BASE) as base:
    names = set(base.namelist())
    for name, path in current.items():
        if name not in names or sha256(base.read(name)).hexdigest() != file_hash(path): files[name] = path
for name in ('reviews/2026-10-26-c-closeout.md', 'experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name] = ROOT / name
for path in AREA.rglob('*.json'):
    if 'node_modules' not in path.parts:
        files['evidence/closeout/' + path.relative_to(AREA).as_posix()] = path
for arm in ('B', 'C'):
    reg = read(AREA / ('runtime-' + arm + '.json'))
    files['evidence/fixture-' + arm + '-binding.json'] = Path(reg['fixture_root']) / 'transport-binding.json'
index = dict(format='review_fixture_integration_and_capsule_delta_v1', base=str(BASE), base_sha256=file_hash(BASE),
    source_manifest={name: file_hash(path) for name, path in source.items()}, files={name: file_hash(path) for name, path in files.items()},
    scope='Both fixture routes integrated; failed bounded review; offline capsule and actual fresh receiver admission only',
    known_review_tokens=644921, review_usage_complete=False, model_closeout_passed=False,
    zero_model_receiver_passed=True, formal_BC_pairs_started=0,
    omitted=['dependencies', 'raw native histories', 'database bytes', 'screenshot duplicate bytes'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items(): archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=file_hash(TARGET), bytes=TARGET.stat().st_size, source_files=len(source),
    delta_files=len(files), base_sha256=index['base_sha256'], scope=index['scope'])
save(Path(__file__).parent / 'closeout-delivery.json', receipt)
print(receipt)
