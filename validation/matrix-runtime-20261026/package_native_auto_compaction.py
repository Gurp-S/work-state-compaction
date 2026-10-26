"""Preserve actual partial capability proof, prior failures and accounting."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'versions/20261026-compaction-feasibility-v0.5-delta.zip'
TARGET = ROOT / 'versions/20261026-native-auto-compaction-capability-v0.6-delta.zip'
AREA = Path('D:/agent-task-runs/native-auto-compaction-20261026-v4')
hashfile = lambda path: sha256(path.read_bytes()).hexdigest()
audit = json.loads((AREA / 'audit-v2.json').read_text(encoding='utf-8'))
assert audit['runtime_auto_compaction'] and not audit['post_compaction_native_tool_access_proven']
assert all(hashfile(AREA / name) == value for name, value in audit['inputs_sha256'].items())
files = {}
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md', 'reviews/2026-10-26-native-auto-compaction-result.md',
    'validation/matrix-runtime-20261026/probe_native_auto_compaction.py',
    'validation/matrix-runtime-20261026/audit_native_auto_compaction.py',
    'validation/matrix-runtime-20261026/package_native_auto_compaction.py'):
    files[name] = ROOT / name
for version in ('v1', 'v2', 'v3', 'v4'):
    folder = Path('D:/agent-task-runs/native-auto-compaction-20261026-' + version)
    for name in ('registration.json', 'grant.json', 'threshold-readback.json', 'interpreter-preflight.json',
        'result.json', 'phase-journal.json', 'next-admission-envelope.json', 'process-observations.json',
        'controller.py', 'audit.json', 'audit-v2.json'):
        path = folder / name
        if path.is_file():
            files['evidence/native-auto-compaction/' + version + '/' + name] = path
index = dict(format='native_auto_compaction_capability_v0.6', base=str(BASE), base_sha256=hashfile(BASE),
    files={name: hashfile(path) for name, path in files.items()},
    known_tokens=135570, known_responses=5, actual_model_trials=2, preflight_only_attempts=2,
    same_turn_auto_compaction_proven=True, OS_process_continuity_observed=True,
    post_compaction_native_session_access_proven=False, WSC_benefit_proven=False,
    whole_campaign_usage_complete=False,
    excluded=['native histories', 'reasoning contents', 'runtime dependencies', 'databases'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(path=str(TARGET), sha256=hashfile(TARGET), bytes=TARGET.stat().st_size, files=len(files))
with (AREA / 'delivery.json').open('x', encoding='utf-8') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
