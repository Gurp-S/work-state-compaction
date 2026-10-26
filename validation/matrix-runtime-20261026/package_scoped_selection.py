"""Archive the single selection and source-bound semantic review; omit runtimes."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, file_hash, save

AREA = Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
BASE = ROOT / 'versions/20261026-real-development-time-policy-and-scoped-state-v1-delta.zip'
TARGET = ROOT / 'versions/20261026-scoped-selection-and-visual-state-v1-delta.zip'
result = read(AREA/'result.json')
assert result['selection_transport_passed'] and result['cleanup']['empty_confirmed']
assert not result['ledger']['inflight'] and not result['ledger']['study']['uncertain']
assert not read(AREA/'semantic-review.json')['development_gate_passed']
assert read(AREA/'S2-clipping-check/result.json')['clipping_observed']
source = {path.relative_to(ROOT).as_posix(): path for folder in ('src','experiments','tests')
    for path in (ROOT/folder).rglob('*.py')}
files = {}
with zipfile.ZipFile(BASE) as base:
    names = set(base.namelist())
    for name,path in source.items():
        if name not in names or sha256(base.read(name)).hexdigest()!=file_hash(path):files[name]=path
    for path in Path(__file__).parent.iterdir():
        if path.is_file() and path.suffix in ('.py','.mjs'):
            name=path.relative_to(ROOT).as_posix()
            if name not in names or sha256(base.read(name)).hexdigest()!=file_hash(path):files[name]=path
for name in ('reviews/2026-10-26-scoped-selection.md','experiments/NATIVE-LOCAL-HANDOFF.md'):
    files[name]=ROOT/name
for path in AREA.rglob('*.json'):
    relative=path.relative_to(AREA)
    if not any(part in ('workspace','cold-public','cold-objects','node_modules') for part in relative.parts):
        files['evidence/scoped-selection/'+relative.as_posix()]=path
image=AREA/'S2-clipping-check/after-wheel.png'
files['evidence/scoped-selection/S2-clipping-check/after-wheel.png']=image
index=dict(format='scoped_selection_and_visual_state_v1',base=str(BASE),base_sha256=file_hash(BASE),
    source_manifest={name:file_hash(path) for name,path in source.items()},
    files={name:file_hash(path) for name,path in files.items()},model_selection_attempts=1,development_started=False,
    selected_view_exported=True,semantic_revision_pending=True,whole_campaign_usage_complete=False,
    scope='One scoped selection; corrected declarations and smaller hot state; confirmed visual risk needs incremental revision',
    excluded=['dependencies','browser binaries','raw native histories','database copies'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(version=str(TARGET),sha256=file_hash(TARGET),bytes=TARGET.stat().st_size,
    source_files=len(source),delta_files=len(files),scope=index['scope'])
save(Path(__file__).parent/'scoped-selection-delivery.json',receipt)
print(receipt)
