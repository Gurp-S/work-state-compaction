"""Archive closed C trial, baseline/host diagnostics, and its isolated source delta."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
WORK=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace')
BASE=ROOT/'versions/20261026-incremental-visual-selection-v1-delta.zip'
TARGET=ROOT/'versions/20261026-incremental-c-development-v1-delta.zip'
review=read(AREA/'closed-review.json')
assert review['cleanup_empty'] and review['independent_functional_passes']==17 and not review['native_completed']
files={}
for name in ('prepare_incremental_dev.py','run_incremental_dev.py','audit_incremental_component_ab.py','close_incremental_dev.py','package_incremental_dev.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for name in ('reviews/2026-10-26-incremental-c-development.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for path in AREA.glob('*.json'):files['evidence/incremental-c/'+path.name]=path
for folder in ('receiver','browser-capability','cold-access','S3-acceptance','S3-concurrency','S3-scope','S3-clipping',
               'S3-production-shell-clipping','S2-production-shell-clipping','component-source-ab',
               'component-source-ab/baseline','component-source-ab/candidate'):
 for path in (AREA/folder).glob('*'):
  if path.is_file() and path.suffix in ('.json','.png','.txt'):
   files['evidence/incremental-c/'+path.relative_to(AREA).as_posix()]=path
for name in review['code_changes']:files['isolated-C-source/'+name]=WORK/name
path=AREA/'fixture-with-production-shell/harness/main.tsx'
files['evidence/incremental-c/fixture-with-production-shell/harness/main.tsx']=path
index=dict(format='incremental_c_development_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(path) for name,path in files.items()},native_completed=False,independent_functional_passes=17,
 component_baseline='27 passed and 9 failed on both original S2 and current source with identical original tests',
 host_diagnostic='Original inner-body host clips; existing production PageShell wrapper scrolls on both S2 and current source',
 whole_campaign_usage_complete=False,formal_BC_started=False,
 excluded=['dependencies','browser binaries','raw native histories','database copies','component source copies','environment files'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,path in files.items():archive.write(path,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),
 scope='Closed failed C admission with 17 functional passes and zero-model baseline/host diagnostics; no BC benefit proof')
save(Path(__file__).parent/'incremental-c-development-delivery.json',receipt)
print(receipt)
