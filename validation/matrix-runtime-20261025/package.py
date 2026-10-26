"""Archive the executed runtime revision and stable boundary evidence only."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash

AREA=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')
reg=read(AREA/'registration.json')
assert all(file_hash(path)==value for path,value in reg['pins'].items())
base=read(ROOT/'validation/application-freeze-20261025/delivery.json')
assert file_hash(base['version'])==base['sha256']
source={p.relative_to(ROOT).as_posix():file_hash(p) for folder in ('src','experiments','tests')
        for p in sorted((ROOT/folder).rglob('*.py'))}
files={name:ROOT/name for name in source}
for path in HERE.rglob('*'):
    if path.is_file() and '__pycache__' not in path.parts and path.name!='delivery.json':
        files[path.relative_to(ROOT).as_posix()]=path
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md','reviews/2026-10-25-native-matrix-runtime.md'):
    files[name]=ROOT/name
for area in ('wsc-nested-fork-observation-20261025-v1','wsc-live-boundary-qualification-20261025-v1',
             'wsc-live-boundary-completion-20261025-v2','wsc-host-controls-20261025-v1','wsc-host-controls-20261025-v2'):
    root=Path('D:/agent-task-runs')/area
    for path in root.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            files['evidence/'+area+'/'+path.relative_to(root).as_posix()]=path
old=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v2')
for path in [old/'registration.json',old/'wave-0-ledger.json',old/'wave-0-settlement.json',
             *old.glob('admission/**/*.json'),*old.glob('trajectories/*/r1/*/output/**/*')]:
    if path.is_file():
        files['evidence/failed-zero-inference-v2/'+path.relative_to(old).as_posix()]=path
files['evidence/study-v3/registration.json']=AREA/'registration.json'
for path in AREA.glob('admission/**/*-0.json'):
    files['evidence/study-v3/'+path.relative_to(AREA).as_posix()]=path
index=dict(format='native_matrix_runtime_v3_source_and_boundary_evidence',
    captured_at=datetime.now(timezone.utc).isoformat(),base=base['version'],base_sha256=base['sha256'],
    source_manifest=source,files={name:file_hash(path) for name,path in files.items()},
    excluded=['installed dependencies','in-flight model response files','full formal study conclusion'],
    scope='Executed native runtime source; small live boundary and bootstrap repair proof; first application wave still running')
version=ROOT/'versions/20261025-native-matrix-runtime-v3-delta.zip'
with zipfile.ZipFile(version,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():
        archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(version),sha256=file_hash(version),bytes=version.stat().st_size,
    source_files=len(source),files=len(files),captured_at=index['captured_at'],
    source_pins_match_live_registration=True,study_complete=False)
save(HERE/'delivery.json',receipt)
print(json.dumps(receipt))
