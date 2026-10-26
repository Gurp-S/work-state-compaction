"""Archive closed calibrated C trial, cost evidence and unimplemented redesign."""
from pathlib import Path
from hashlib import sha256
import sys,json,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
WORK=Path(read(AREA/'registration.json')['session']['workspace'])
BASE=ROOT/'versions/20261026-calibrated-incremental-selection-v1-delta.zip'
TARGET=ROOT/'versions/20261026-calibrated-c-s3-and-context-proposal-v1-delta.zip'
r=read(AREA/'closed-review.json');assert r['cleanup_empty'] and r['independent_functional_passes']==17
files={}
for name in ('prepare_calibrated_dev.py','run_calibrated_dev.py','close_calibrated_dev.py','package_calibrated_dev.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for name in ('reviews/2026-10-26-calibrated-c-s3-result.md','reviews/2026-10-26-stage-context-redesign-proposal.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for p in AREA.glob('*.json'):files['evidence/calibrated-c/'+p.name]=p
for folder in ('receiver','browser-capability','cold-access','S3-acceptance','S3-concurrency','S3-scope','S3-clipping'):
 for p in (AREA/folder).glob('*'):
  if p.is_file() and p.suffix in ('.json','.txt','.png'):
   files['evidence/calibrated-c/'+p.relative_to(AREA).as_posix()]=p
for name in r['code_changes']:files['isolated-C-source/'+name]=WORK/name
schema=AREA/'native-protocol-schema'
for name in ('ClientRequest.json','v2/ThreadCompactStartParams.json','v2/ThreadInjectItemsParams.json','v2/TurnStartParams.json','v2/TurnInterruptParams.json'):
 files['evidence/calibrated-c/native-protocol-schema/'+name]=schema/name
index=dict(format='calibrated_c_s3_context_proposal_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(p) for name,p in files.items()},known_tokens=6035553,known_responses=44,
 whole_campaign_usage_complete=False,native_completed=False,functional_passes=17,
 redesign_implemented=False,formal_BC_started=False,
 scope='Closed C cap failure, scoped functional evidence, input-growth audit and structural proposal; no relative native benefit proof',
 excluded=['dependencies','browser binaries','raw native histories','database copies','complete protocol schema bundle'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,p in files.items():archive.write(p,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),scope=index['scope'])
save(Path(__file__).parent/'calibrated-c-development-delivery.json',receipt)
print(receipt)
