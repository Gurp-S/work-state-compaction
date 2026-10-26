"""Archive feasibility evidence and superseding proposal, not runtime benefit."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'versions/20261026-controlled-stop-result-and-v0.4-proposal-delta.zip'
TARGET = ROOT / 'versions/20261026-compaction-feasibility-v0.5-delta.zip'
hashfile = lambda path: sha256(path.read_bytes()).hexdigest()
files = {}
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md', 'reviews/2026-10-26-stage-compaction-feasibility-v0.5.md',
    'validation/matrix-runtime-20261026/audit_native_compaction_feasibility.py',
    'validation/matrix-runtime-20261026/package_compaction_feasibility.py'):
    files[name] = ROOT / name
for version in ('v1', 'v2'):
    area = Path('D:/agent-task-runs/native-compaction-feasibility-20261026-' + version)
    for name in ('audit.json', 'next-admission-envelope.json'):
        files['evidence/compaction-feasibility/' + version + '/' + name] = area / name
audit = json.loads(files['evidence/compaction-feasibility/v2/audit.json'].read_text(encoding='utf-8'))
assert audit['model_calls'] == 0 and not audit['config_written'] and not audit['benefit_proven']
assert audit['records'][1]['config_projection']['model_auto_compact_token_limit'] == 96000
assert all('error' not in record and record['cleanup']['empty_confirmed'] for record in audit['records'])
index = dict(format='native_compaction_feasibility_v0.5', base=str(BASE), base_sha256=hashfile(BASE),
    files={name: hashfile(path) for name, path in files.items()}, model_calls=0,
    config_override_readback_observed=True, runtime_compaction_proven=False, benefit_proven=False,
    native_B_changed=False, whole_campaign_usage_complete=False,
    scope='Offline teardown feasibility review and isolated native config readback; no implementation or continuation proof')
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(path=str(TARGET), sha256=hashfile(TARGET), bytes=TARGET.stat().st_size, files=len(files))
with (Path('D:/agent-task-runs/native-compaction-feasibility-20261026-v2') / 'delivery.json').open('x', encoding='utf-8') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
