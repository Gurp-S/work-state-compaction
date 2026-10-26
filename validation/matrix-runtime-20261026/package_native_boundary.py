"""Seal one held-tool capability observation and unimplemented v0.2 design."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/native-boundary-capability-20261026-v3')
BASE=ROOT/'versions/20261026-calibrated-c-s3-and-context-proposal-v1-delta.zip'
TARGET=ROOT/'versions/20261026-controlled-checkpoint-capability-v0.2-delta.zip'
a=read(AREA/'audit.json');assert a['real_model_attempts']==1 and a['cleanup_empty'] and not a['safe_in_place_checkpoint_proven']
files={}
for name in ('reviews/2026-10-26-native-held-boundary-capability.md','reviews/2026-10-26-controlled-checkpoint-design-v0.2.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for name in ('probe_native_held_boundary.py','audit_native_held_boundary.py','package_native_boundary.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for version in ('v1','v2','v3'):
 area=Path('D:/agent-task-runs/native-boundary-capability-20261026-'+version)
 for p in area.glob('*.json'):
  if p.name!='held-thread-read.json':files['evidence/native-held/'+version+'/'+p.name]=p
schema=Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1/native-protocol-schema')
for name in ('DynamicToolCallParams.json','DynamicToolCallResponse.json','ServerRequest.json','v2/ThreadStartParams.json'):
 files['evidence/native-held/protocol/'+name]=schema/name
index=dict(format='controlled_checkpoint_capability_v0.2',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(p) for name,p in files.items()},real_model_attempts=1,known_tokens=22497,
 whole_campaign_usage_complete=False,complete_probe_usage=None,application_development=False,
 safe_in_place_checkpoint_proven=False,controlled_handoff_implemented=False,
 scope='One dynamic callback waiting point; original turn replaced by compact, later accounting incomplete; design only',
 excluded=['raw native histories','reasoning item contents','runtime dependencies','browsers','database copies'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,p in files.items():archive.write(p,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),scope=index['scope'])
save(Path(__file__).parent/'native-boundary-delivery.json',receipt)
print(receipt)
