"""Seal opt-in evaluation applicability correction as a small source/evidence delta."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,file_hash,save
AREA=Path('D:/agent-task-runs/wsc-evaluation-context-20261026-v1')
BASE=ROOT/'versions/20261026-incremental-c-development-v1-delta.zip'
TARGET=ROOT/'versions/20261026-evaluation-context-calibration-v1-delta.zip'
assert read(AREA/'calibration-review.json')['model_calls']==0
files={}
for name in ('experiments/native_evaluation_context.py','experiments/native_evaluation_host.py',
             'tests/test_native_evaluation_context.py','reviews/2026-10-26-evaluation-context-calibration.md',
             'experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for name in ('calibrate_evaluation_context.py','package_evaluation_context.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for path in AREA.glob('*.json'):files['evidence/evaluation-context/'+path.name]=path
for folder in ('S2','C_S3','C-S3-cumulative'):
 for path in (AREA/folder).glob('*'):
  if path.is_file() and path.suffix in ('.json','.png','.txt'):
   files['evidence/evaluation-context/'+path.relative_to(AREA).as_posix()]=path
for path in (AREA/'production-panel-host').rglob('*'):
 if path.is_file():files['evidence/evaluation-context/'+path.relative_to(AREA).as_posix()]=path
source=read(AREA/'goal-source.json');goal=Path(source['path'])
assert file_hash(goal)==source['sha256']
files['evidence/goal-source.md']=goal
index=dict(format='evaluation_context_calibration_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(path) for name,path in files.items()},new_model_calls=0,paid_development_started=False,
 original_defaults_unchanged=True,paired_driver_integrated=False,
 scope='Opt-in host/applicability correction; 6 focused unit checks, 2 geometry probes, 11 cumulative checks; no native BC benefit proof')
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,path in files.items():archive.write(path,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),
 model_calls=0,scope=index['scope'])
save(Path(__file__).parent/'evaluation-context-delivery.json',receipt)
print(receipt)
