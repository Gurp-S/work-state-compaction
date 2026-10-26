"""Archive source and receipt pointers without copying browser images."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash

review = read(OUT / 'review.json')
assert review['production_gui_source_unchanged'] and review['new_model_calls'] == 0
base = read(ROOT / 'validation/task-matrix-20261023/delivery.json')
assert file_hash(base['version']) == base['sha256']
with zipfile.ZipFile(base['version']) as archive:
    old = json.loads(archive.read('VERSION.json'))
source = {p.relative_to(ROOT).as_posix(): file_hash(p)
          for folder in ('src', 'experiments', 'tests')
          for p in sorted((ROOT / folder).rglob('*.py'))}
assert source == old['source_manifest']
files = {}
for folder in (OUT, ROOT / 'benchmarks/a3-ui-long-v1', ROOT / 'benchmarks/application-five-task-v1'):
    for p in folder.rglob('*'):
        if p.is_file() and p.name != 'delivery.json':
            name = p.relative_to(ROOT).as_posix()
            if old['files'].get(name) != file_hash(p):
                files[name] = p
name = 'experiments/NATIVE-LOCAL-HANDOFF.md'
files[name] = ROOT / name
index = dict(format='a3_acceptance_delta', base=base['version'], base_sha256=base['sha256'],
             source_manifest=source, files={n: file_hash(p) for n, p in files.items()},
             scope='Offline browser calibration only; full positive/manual qualification pending',
             review_sha256=file_hash(OUT / 'review.json'))
version = ROOT / 'versions/20261023-a3-browser-acceptance-v1-delta.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest() == h for n, h in index['files'].items())
receipt = dict(version=str(version), bytes=version.stat().st_size, sha256=file_hash(version),
               source_files=len(source), new_model_calls=0, goal_complete=False)
save(OUT / 'delivery.json', receipt)
print(json.dumps(receipt, ensure_ascii=False))
