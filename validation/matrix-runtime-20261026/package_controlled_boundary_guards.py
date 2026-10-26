"""Preserve opt-in boundary guards; excludes native histories and reasoning."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
AREA = Path('D:/agent-task-runs/wsc-controlled-boundary-guards-20261026-v1')
BASE = ROOT / 'versions/20261026-controlled-checkpoint-capability-v0.2-delta.zip'
TARGET = ROOT / 'versions/20261026-controlled-boundary-guards-v0.3-delta.zip'
hashfile = lambda p: sha256(p.read_bytes()).hexdigest()
names = ['experiments/native_controlled_boundary.py', 'tests/test_native_controlled_boundary.py',
    'reviews/2026-10-26-controlled-boundary-guards.md', 'experiments/NATIVE-LOCAL-HANDOFF.md',
    'validation/matrix-runtime-20261026/audit_controlled_boundary_guards.py',
    'validation/matrix-runtime-20261026/package_controlled_boundary_guards.py']
files = {name: ROOT / name for name in names}
files['evidence/controlled-boundary-guards/audit.json'] = AREA / 'audit.json'
audit = json.loads((AREA / 'audit.json').read_text(encoding='utf-8'))
assert audit['implementation_sha256'] == hashfile(ROOT / names[0])
assert audit['historical_trial_promoted'] is False and audit['real_model_calls'] == 0
index = dict(format='controlled_boundary_guards_v0.3', base=str(BASE), base_sha256=hashfile(BASE),
    files={name: hashfile(path) for name, path in files.items()},
    tests=dict(command='py -3.11 -B -X utf8 -m unittest discover -s wsc/tests -p test_native_controlled_boundary.py',
        observed_passed=19, scope='module-only unit and offline WSC publication fixture; not native installation'),
    real_model_calls=0, native_host_implemented=False, semantic_or_economic_benefit_proven=False,
    whole_campaign_usage_complete=False,
    excluded=['raw native histories', 'reasoning contents', 'runtime dependencies', 'databases'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(version=str(TARGET), sha256=hashfile(TARGET), bytes=TARGET.stat().st_size,
    files=len(files), scope=index['tests']['scope'])
with (AREA / 'delivery.json').open('x', encoding='utf-8') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
