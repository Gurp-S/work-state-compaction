"""Seal paired evaluation hooks and zero-inference admission without private runtimes."""
from pathlib import Path
from hashlib import sha256
import sys,json,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')
BASE=ROOT/'versions/20261026-evaluation-context-calibration-v1-delta.zip'
TARGET=ROOT/'versions/20261026-paired-evaluation-integration-v1-delta.zip'
assert read(AREA/'result.json')['model_calls']==0
files={}
for name in ('native_paired_evaluation.py','native_evaluation_host.py','native_evaluation_context.py',
 'native_application_adapters.py','native_application_worker.py','native_fixture_transport.py'):
 files['experiments/'+name]=ROOT/'experiments'/name
for name in ('test_native_evaluation_context.py','test_native_shared_worker.py'):
 files['tests/'+name]=ROOT/'tests'/name
for name in ('admit_paired_evaluation.py','continue_paired_native_admission.py','package_paired_evaluation.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for name in ('reviews/2026-10-26-paired-evaluation-integration.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for path in AREA.glob('*'):
 if path.is_file() and path.suffix in ('.json','.py'):
  files['evidence/paired-evaluation/'+path.name]=path
for folder in ('S2-geometry','S2-after-port-error-geometry',
 'B','C','B/native-receiver','B/native-receiver-v2','C/native-receiver-v2',
 'B/native-cold-check','C/native-cold-check','B/S2-routed-grade','B/S2-routed-grade-driver'):
 for p in (AREA/folder).glob('*'):
  if p.is_file() and p.suffix in ('.json','.png','.txt'):
   files['evidence/paired-evaluation/'+p.relative_to(AREA).as_posix()]=p
index=dict(format='paired_evaluation_integration_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(p) for name,p in files.items()},model_calls=0,real_native_receivers=2,
 hooks_integrated=True,writable_development_qualified=False,formal_BC_started=False,
 scope='Prepare/grade/worker integration, read-only native facts import and cold access; not WSC economic benefit',
 excluded=['dependencies','browsers','workspace copies','databases','raw native histories'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,p in files.items():archive.write(p,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),model_calls=0,scope=index['scope'])
save(Path(__file__).parent/'paired-evaluation-delivery.json',receipt)
print(receipt)
