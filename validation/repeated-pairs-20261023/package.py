"""Small preparation delta; never reruns checks or model/browser experiments."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT/'experiments'))
from native_evidence import file_hash, read, save

checks = read(OUT/'after-checks.json')
assert checks['passed'] and checks['tests'] == 9
assert all(file_hash(ROOT/name) == value for name,value in checks['source_manifest'].items())
base = read(ROOT/'validation/fork-admission-20261023/delivery.json')
assert file_hash(ROOT.parent/base['version']) == base['sha256']
source = {p.relative_to(ROOT).as_posix(): file_hash(p) for folder in ('src','experiments','tests')
          for p in sorted((ROOT/folder).rglob('*.py'))}
old = read(ROOT/'validation/fork-admission-20261023/checks.json')['source_manifest']
changed = [name for name,value in source.items() if old.get(name) != value]
assert set(changed) == {'experiments/native_repeated_pairs.py', 'tests/test_native_repeated_pairs.py'}
assert not set(old)-set(source)
files = {name: ROOT/name for name in changed}
for folder in (OUT, ROOT/'benchmarks/a3-ui-long-v1'):
    for p in folder.rglob('*'):
        if p.is_file() and p.name != 'delivery.json':
            files[p.relative_to(ROOT).as_posix()] = p
for name in ('experiments/BC-REPLICATION-POLICY.md','experiments/BC-UI-REVIEW-RUBRIC.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name] = ROOT/name
index = dict(format='source_delta_and_benchmark_preparation', base=base['version'], base_sha256=base['sha256'],
             source_manifest=source, changed_sources=changed, files={n:file_hash(p) for n,p in files.items()},
             scope='Offline scheduling validated; browser baseline scope recorded separately; no paid B/C launched')
version = ROOT/'versions/20261023-repeated-pairs-a3-preparation-v1.zip'
with zipfile.ZipFile(version, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name,p in files.items():
        archive.write(p,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest()==h for n,h in index['files'].items())
receipt = dict(version=str(version), bytes=version.stat().st_size, sha256=file_hash(version),
               tests=9, source_files=len(source), new_model_calls=0, goal_complete=False)
save(OUT/'delivery.json',receipt)
print(json.dumps(receipt,ensure_ascii=False))
