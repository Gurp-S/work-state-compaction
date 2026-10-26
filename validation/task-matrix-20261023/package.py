"""Retain a compact delta for the new five-task repetition contract."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import file_hash,read,save

checks=read(OUT/'checks.json')
assert checks['passed'] and checks['tests']==16
source={p.relative_to(ROOT).as_posix():file_hash(p) for folder in ('src','experiments','tests')
        for p in sorted((ROOT/folder).rglob('*.py'))}
assert source==checks['source_manifest']
base=read(ROOT/'validation/repeated-pairs-20261023/delivery.json')
assert file_hash(base['version'])==base['sha256']
with zipfile.ZipFile(base['version']) as archive:
    old=json.loads(archive.read('VERSION.json'))['source_manifest']
changed=[p for p,h in source.items() if old.get(p)!=h]
assert set(changed)=={'experiments/native_repeated_pairs.py','experiments/native_task_matrix.py','tests/test_native_task_matrix.py'}
assert not set(old)-set(source)
files={p:ROOT/p for p in changed}
for folder in (OUT,ROOT/'benchmarks/a3-ui-long-v1',ROOT/'benchmarks/application-five-task-v1'):
    for p in folder.rglob('*'):
        if p.is_file() and p.name!='delivery.json': files[p.relative_to(ROOT).as_posix()]=p
for name in ('experiments/BC-REPLICATION-POLICY.md','experiments/BC-UI-REVIEW-RUBRIC.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name]=ROOT/name
index=dict(format='source_delta_and_five_task_contract',base=base['version'],base_sha256=base['sha256'],
    source_manifest=source,changed_sources=changed,files={n:file_hash(p) for n,p in files.items()},
    scope='16 offline scheduler checks and 11 fixture scenarios; no paid experiment or full browser acceptance')
version=ROOT/'versions/20261023-five-task-matrix-v1-delta.zip'
with zipfile.ZipFile(version,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for n,p in files.items(): archive.write(p,n)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(n)).hexdigest()==h for n,h in index['files'].items())
receipt=dict(version=str(version),bytes=version.stat().st_size,sha256=file_hash(version),source_files=len(source),
             scoped_checks=16,fixture_scenarios=11,new_model_calls=0,goal_complete=False)
save(OUT/'delivery.json',receipt)
print(json.dumps(receipt,ensure_ascii=False))
