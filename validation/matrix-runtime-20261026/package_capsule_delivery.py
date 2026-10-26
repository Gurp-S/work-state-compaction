"""Seal the completed small model delivery without duplicating raw histories."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-a3-capsule-review-20261026-v1')
BASE = ROOT / 'versions/20261026-review-fixture-integration-and-capsule-v1-delta.zip'
TARGET = ROOT / 'versions/20261026-capsule-model-delivery-v1-delta.zip'
result = read(AREA / 'result.json')
assert result['fact_delivery_passed'] and result['cleanup']['empty_confirmed']
assert not result['ledger']['inflight'] and not result['ledger']['study']['uncertain']
files = {}
for name in ('reviews/2026-10-26-capsule-fact-delivery.md', 'experiments/NATIVE-LOCAL-HANDOFF.md',
    'validation/matrix-runtime-20261026/run_capsule_review.py', 'validation/matrix-runtime-20261026/package_capsule_delivery.py'):
    files[name] = ROOT / name
for path in AREA.rglob('*.json'):
    files['evidence/capsule-delivery/' + path.relative_to(AREA).as_posix()] = path
index = dict(format='capsule_model_delivery_v1', base=str(BASE), base_sha256=file_hash(BASE),
    files={name: file_hash(path) for name, path in files.items()}, model_phase_passed=True,
    phase_usage_complete=True, whole_campaign_usage_complete=False, full_development_qualification=False,
    scope='One actual fact-only model delivery, not a full development or causal B/C result',
    omitted=['dependencies', 'raw native histories', 'database bytes'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items(): archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=file_hash(TARGET), bytes=TARGET.stat().st_size,
    files=len(files), base_sha256=index['base_sha256'], scope=index['scope'])
save(Path(__file__).parent / 'capsule-model-delivery.json', receipt)
print(receipt)
