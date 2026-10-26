"""Seal the one incremental selection receipt and current scoped sources."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1')
BASE=ROOT/'versions/20261026-scoped-selection-and-visual-state-v1-delta.zip'
TARGET=ROOT/'versions/20261026-incremental-visual-selection-v1-delta.zip'
assert read(AREA/'semantic-review.json')['semantic_selection_gate_passed']
assert read(AREA/'result.json')['cleanup']['empty_confirmed']
source={p.relative_to(ROOT).as_posix():p for folder in ('src','experiments','tests') for p in (ROOT/folder).rglob('*.py')}
files={}
with zipfile.ZipFile(BASE) as base:
    index=json.loads(base.read('VERSION.json'))
    assert index['source_manifest']=={name:file_hash(path) for name,path in source.items()}, 'implementation_changed_after_prior_seal'
for name in ('revise_incremental_visual.py','review_incremental_visual.py','package_incremental_visual.py'):
    path=Path(__file__).parent/name;files[path.relative_to(ROOT).as_posix()]=path
for name in ('reviews/2026-10-26-incremental-visual-selection.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name]=ROOT/name
for path in AREA.rglob('*.json'):
    rel=path.relative_to(AREA)
    if not any(part in ('workspace','cold-public','cold-objects','node_modules') for part in rel.parts):
        files['evidence/incremental-visual/'+rel.as_posix()]=path
index=dict(format='incremental_visual_selection_v1',base=str(BASE),base_sha256=file_hash(BASE),
    files={name:file_hash(path) for name,path in files.items()},model_calls=1,
    semantic_selection_gate_passed=True,development_started=False,whole_campaign_usage_complete=False,
    excluded=['database copies','dependencies','raw native histories','cold objects already stored locally'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,delta_files=len(files),
    semantic_selection_gate_passed=True,scope='One incremental selection; evidence and semantic review, no development or BC benefit proof')
save(Path(__file__).parent/'incremental-visual-delivery.json',receipt)
print(receipt)
