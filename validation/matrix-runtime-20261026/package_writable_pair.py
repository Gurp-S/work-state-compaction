"""Seal physical-runtime admission and locator-only baseline correction."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1')
BASE=ROOT/'versions/20261026-paired-evaluation-integration-v1-delta.zip'
TARGET=ROOT/'versions/20261026-writable-pair-and-component-baseline-v1-delta.zip'
assert read(AREA/'result.json')['parallel_writable_native_admission_passed']
assert read(AREA/'component-locator-calibration/result.json')['negative_control_rejected']
files={}
for name in ('prepare_writable_pair.py','check_writable_pair.py','calibrate_component_locators.py','package_writable_pair.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for name in ('reviews/2026-10-26-writable-pair-and-component-baseline.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for p in AREA.glob('*.json'):files['evidence/writable-pair/'+p.name]=p
for folder in ('B','C','B/receiver','C/receiver','B/generic-browser-capability','C/generic-browser-capability','component-locator-calibration'):
 for p in (AREA/folder).glob('*'):
  if p.is_file() and p.suffix in ('.json','.txt','.png'):
   files['evidence/writable-pair/'+p.relative_to(AREA).as_posix()]=p
for name in ('A3NativePanel.test.tsx','A3SnapshotPanel.test.tsx'):
 p=AREA/'component-locator-calibration/gui/src/components'/name
 files['evidence/locator-test-variant/'+name]=p
for arm in ('B','C'):
 execution=read(AREA/arm/'A3-browser-execution.json')
 observation=read(AREA/arm/'A3-observation.json')
 for key in ('registration','result'):
  p=Path(observation[key]['path']);files['evidence/writable-pair/'+arm+'/actual-A3/'+p.name]=p
 p=Path(observation['result']['path']).parent/'after-wheel.png'
 files['evidence/writable-pair/'+arm+'/actual-A3/'+p.name]=p
index=dict(format='writable_pair_and_component_baseline_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(p) for name,p in files.items()},model_calls=0,large_runtime_copies=0,
 parallel_native_writable_admission=True,locator_variant_component_passes=36,wrong_acceptance_negative_failures=3,
 original_frozen_tests_unchanged=True,paid_development_started=False,formal_BC_started=False,
 scope='Real native writable environment plus two-suite locator calibration; no WSC continuation or native comparison benefit proof',
 excluded=['dependencies','browsers','workspace copies','raw native histories','database copies'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,p in files.items():archive.write(p,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),model_calls=0,scope=index['scope'])
save(Path(__file__).parent/'writable-pair-delivery.json',receipt)
print(receipt)
