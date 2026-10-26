"""Small evidence delta for one refused stop and a zero-inference inventory."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'versions/20261026-controlled-boundary-guards-v0.3-delta.zip'
TARGET = ROOT / 'versions/20261026-controlled-stop-result-and-v0.4-proposal-delta.zip'
LIVE = Path('D:/agent-task-runs/native-controlled-stop-20261026-v1')
IDLE = Path('D:/agent-task-runs/native-idle-process-inventory-20261026-v1')
hashfile = lambda path: sha256(path.read_bytes()).hexdigest()
result = json.loads((LIVE / 'result.json').read_text(encoding='utf-8'))
gate = json.loads((LIVE / 'held-gate.json').read_text(encoding='utf-8'))
assert not gate['admitted'] and not result['controlled_stop_sealed'] and not result.get('interrupt_requested')
assert result['settlement']['usage_complete'] and result['settlement']['known_total_tokens'] == 45308
assert result['cleanup']['empty_confirmed']
files = {}
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md', 'reviews/2026-10-26-controlled-stop-real-result.md',
    'reviews/2026-10-26-controlled-teardown-design-v0.4.md',
    'validation/matrix-runtime-20261026/probe_native_controlled_stop.py',
    'validation/matrix-runtime-20261026/inspect_native_idle_processes.py',
    'validation/matrix-runtime-20261026/package_controlled_stop_result.py'):
    files[name] = ROOT / name
for name in ('registration.json', 'grant.json', 'held-gate.json', 'result.json',
             'ordinary-accounting.json', 'phase-journal.json', 'next-admission-envelope.json'):
    files['evidence/controlled-stop/' + name] = LIVE / name
for name in ('result.json', 'next-admission-envelope.json'):
    files['evidence/idle-inventory/' + name] = IDLE / name
index = dict(format='controlled_stop_result_and_v0.4_proposal', base=str(BASE), base_sha256=hashfile(BASE),
    files={name: hashfile(path) for name, path in files.items()},
    raw_evidence_sha256={name: hashfile(LIVE / name) for name in ('events.jsonl', 'held-native.jsonl', 'closed-native.jsonl')},
    known_tokens=45308, known_responses=2, this_probe_usage_complete=True,
    whole_campaign_usage_complete=False, controlled_stop_executed=False, receiver_installed=False,
    v04_implemented=False, benefit_proven=False,
    excluded=['native histories', 'reasoning contents', 'runtime dependencies', 'databases'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(path=str(TARGET), sha256=hashfile(TARGET), bytes=TARGET.stat().st_size, files=len(files))
with (LIVE / 'delivery.json').open('x', encoding='utf-8') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
