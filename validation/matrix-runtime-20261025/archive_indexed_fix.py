"""Small source delta and bounded evidence; no model calls or raw-history copies."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
BASE = ROOT / 'versions/20261025-a3-qualification-runtime-v1-delta.zip'
TARGET = ROOT / 'versions/20261025-shared-s2-indexed-checkpoint-v1-delta.zip'
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
    for p in sorted((ROOT / folder).rglob('*.py'))}
files = {}
with zipfile.ZipFile(BASE) as base:
    names = set(base.namelist())
    for name, value in source.items():
        if name not in names or sha256(base.read(name)).hexdigest() != value:
            files[name] = ROOT / name
    for path in Path(__file__).parent.iterdir():
        if path.is_file() and path.suffix in ('.py', '.txt'):
            name = path.relative_to(ROOT).as_posix()
            if name not in names or sha256(base.read(name)).hexdigest() != file_hash(path):
                files[name] = path
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md', 'reviews/2026-10-25-shared-s2-compression.md',
    'reviews/2026-10-25-a3-qualification.md'):
    files[name] = ROOT / name
for name in ('result.json', 'registration.json', 'S2-grade.json', 'staged/capsule.json',
    'preflight-wire.json', 'oversize-draft-analysis/result.json',
    'arms/C/output/S2-generation/model-draft.json', 'arms/C/output/S2-generation/compiled-draft.json',
    'indexed-view-replay-v2/result.json', 'indexed-view-replay-v2/package.json',
    'indexed-native-import-v1/result.json', 'indexed-native-import-v1/cold-access/execution.json',
    'indexed-native-import-v1/receiver/import-result.json'):
    files['evidence/shared-s2/' + name] = AREA / name
checks = dict(observed_checks=[dict(pattern=pattern, passed=count) for pattern, count in (
    ('test_native_indexed_checkpoint.py', 3), ('test_native_incremental_candidate.py', 8),
    ('test_native_shared_worker.py', 1), ('test_native_application_worker.py', 3))],
    execution='py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p <pattern>',
    source_manifest=source, scope='Observed current-turn execution; scoped tests only, not full project')
index = dict(format='shared_s2_indexed_checkpoint_delta_v1', captured_at=datetime.now(timezone.utc).isoformat(),
    base=str(BASE), base_sha256=file_hash(BASE), source_manifest=source,
    files={name: file_hash(path) for name, path in files.items()}, scoped_checks=checks,
    omitted=['installed dependencies', 'binary browsers', 'raw native histories', 'account identifiers and rate-limit dump'],
    scope='Current opt-in repair, same-draft replay, zero-inference import; no business continuation/benefit proof')
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=file_hash(TARGET), bytes=TARGET.stat().st_size,
    source_files=len(source), delta_files=len(files), base=str(BASE), base_sha256=file_hash(BASE),
    model_calls_for_repair_validation=0, scope=index['scope'])
save(Path(__file__).parent / 'indexed-fix-delivery.json', receipt)
print(receipt)
