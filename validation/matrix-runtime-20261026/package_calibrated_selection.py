"""Seal the single model selection and equivalent-copy replay as a delta."""
from pathlib import Path
from hashlib import sha256
import json,sys,zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
AREA=Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1')
BASE=ROOT/'versions/20261026-writable-pair-and-component-baseline-v1-delta.zip'
TARGET=ROOT/'versions/20261026-calibrated-incremental-selection-v1-delta.zip'
assert read(AREA/'semantic-review.json')['selection_evidence_gate_passed']
assert read(AREA/'result.json')['cleanup']['empty_confirmed']
files={}
for name in ('experiments/native_equivalent_selection_replay.py','tests/test_native_equivalent_selection_replay.py',
 'reviews/2026-10-26-calibrated-incremental-selection.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
 files[name]=ROOT/name
for name in ('generate_calibrated_selection.py','review_calibrated_selection.py','package_calibrated_selection.py'):
 p=Path(__file__).parent/name;files[p.relative_to(ROOT).as_posix()]=p
for folder in ('','generation','material-access','export-access','selector'):
 for p in (AREA/folder).glob('*.json'):files['evidence/calibrated-selection/'+p.relative_to(AREA).as_posix()]=p
package=read(AREA/'package.json')
for name in ('source_index','understanding_index'):
 p=Path(package[name]);files['evidence/calibrated-selection/indexes/'+p.name]=p
index=dict(format='calibrated_incremental_selection_v1',base=str(BASE),base_sha256=file_hash(BASE),
 files={name:file_hash(p) for name,p in files.items()},model_calls=1,selection_total_tokens=76397,
 equivalent_copy_replay=True,selection_evidence_gate_passed=True,model_use_of_evidence_proven=False,
 full_C_qualified=False,formal_BC_started=False,whole_campaign_usage_complete=False,
 scope='One incremental selection and reference audit, no development or relative native benefit proof',
 excluded=['database copies','cold objects','dependencies','browser binaries','raw native histories'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
 for name,p in files.items():archive.write(p,name)
 archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
 assert archive.testzip() is None
 assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,files=len(files),scope=index['scope'])
save(Path(__file__).parent/'calibrated-selection-delivery.json',receipt)
print(receipt)
