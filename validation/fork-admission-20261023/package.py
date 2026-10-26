"""Retain a small source delta and evidence pointers, never rerun native calls."""
from pathlib import Path
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import digest, file_hash, read, save

OUT = Path(__file__).parent
checks = read(OUT / 'checks.json')
assert checks['passed'] and checks['tests'] == 44
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src', 'experiments', 'tests')
          for p in sorted((ROOT / folder).rglob('*.py'))}
assert source == checks['source_manifest']
old = read(ROOT / 'validation/native-transport-20261023/checks.json')['source_manifest']
base = read(ROOT / 'validation/native-transport-20261023/delivery.json')
base_zip = ROOT.parent / base['version']
assert file_hash(base_zip) == base['sha256']
changed = [p for p in source if source[p] != old.get(p)]
deleted = sorted(set(old) - set(source))
assert not deleted
files = {p: ROOT / p for p in changed}
for p in OUT.iterdir():
    if p.is_file() and p.name != 'delivery.json':
        files[p.relative_to(ROOT).as_posix()] = p
for name in ('reviews/2026-10-23-fork-admission-and-accounting.md', 'experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name] = ROOT / name
probe = Path('D:/agent-task-runs/wsc-fork-admission-20261023-v1/single-response-probe')
evidence = {}
for name in ('registration.json', 'result.json', 'parent-counters.json',
             'history-binding.json', 'reviewed-accounting.json'):
    p = probe / name
    evidence[name] = {'path': str(p), 'sha256': file_hash(p)}
    files['evidence/' + name] = p
version = ROOT / 'versions/20261023-fork-admission-v1-delta.zip'
index = {'format': 'source_delta_with_evidence', 'base': base['version'], 'base_sha256': base['sha256'],
         'source_manifest': source, 'changed_sources': changed, 'deleted_sources': deleted,
         'files': {name: file_hash(p) for name, p in files.items()}, 'probe_evidence': evidence}
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, p in files.items():
        archive.write(p, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    from hashlib import sha256
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
delivery = {'version': str(version.relative_to(ROOT.parent)), 'sha256': file_hash(version),
            'bytes': version.stat().st_size, 'source_files': len(source),
            'source_manifest_sha256': digest(source), 'checks_sha256': file_hash(OUT / 'checks.json'),
            'tests': checks['tests'], 'changed_sources': changed, 'probe_evidence': evidence,
            'new_model_calls_in_protocol_probe': 1, 'protocol_probe_tokens': 26955,
            'new_model_calls_in_validation': 0, 'shared_phase_paid_task_verified': False,
            'goal_complete': False}
save(OUT / 'delivery.json', delivery)
print(json.dumps({k: delivery[k] for k in ('version', 'bytes', 'source_files', 'tests', 'sha256', 'changed_sources')}, ensure_ascii=False))
