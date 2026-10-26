"""Freeze the admitted A3 qualification source, not in-flight task results."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash

AREA=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1')
reg=read(AREA/'registration.json')
assert all(file_hash(path)==value for path,value in reg['pins'].items())
base=read(HERE/'closure-delivery.json')
assert file_hash(base['version'])==base['sha256']
source={path.relative_to(ROOT).as_posix():file_hash(path) for folder in ('src','experiments','tests')
        for path in sorted((ROOT/folder).rglob('*.py'))}
files={name:ROOT/name for name in ('experiments/native_campaign_envelope.py','tests/test_native_campaign_envelope.py',
    'validation/matrix-runtime-20261025/a3_pilot.py','validation/matrix-runtime-20261025/pilot_status.py',
    'validation/matrix-runtime-20261025/package_a3_pilot.py','experiments/NATIVE-LOCAL-HANDOFF.md',
    'reviews/2026-10-25-a3-qualification.md')}
for path in [AREA/'registration.json',AREA/'prepared.json',*AREA.glob('prepared/*.json'),
             *AREA.glob('preparation/*/*.json'),*AREA.glob('admission/**/*-0.json'),
             *AREA.glob('arms/*/output/initial/opened.jsonl'),*AREA.glob('arms/*/output/initial/registration.json')]:
    files['evidence/a3-qualification/'+path.relative_to(AREA).as_posix()]=path
path=Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1/result.json')
files['evidence/preparation-protocol-included/result.json']=path
index=dict(format='a3_qualification_admitted_runtime_delta',captured_at=datetime.now(timezone.utc).isoformat(),
    base=base['version'],base_sha256=base['sha256'],source_manifest=source,
    files={name:file_hash(path) for name,path in files.items()},historical_envelope=reg['envelope'],
    scope='Source/input/admission qualification version; model tasks still in flight, no completion or benefit conclusion')
version=ROOT/'versions/20261025-a3-qualification-runtime-v1-delta.zip'
with zipfile.ZipFile(version,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():
        archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(version) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(version),bytes=version.stat().st_size,sha256=file_hash(version),
    source_files=len(source),files=len(files),model_tasks_still_in_flight=True,new_model_calls=0)
save(HERE/'a3-runtime-delivery.json',receipt)
print(json.dumps(receipt))
