"""Measure the exact failed draft on a database backup; no inference or install."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from wsc import WSC,Store
from wsc.contracts import Limits,encode
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from native_incremental_candidate import frontier,compile_draft,POLICY
from native_evidence import read,save,file_hash

AREA=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT=AREA/'oversize-draft-analysis'
OUT.mkdir(exist_ok=False)
original=AREA/'arms/C/output'
before=file_hash(original/'wsc.db')
source=sqlite3.connect('file:'+str(original/'wsc.db')+'?mode=ro',uri=True)
target=sqlite3.connect(OUT/'wsc.db')
source.backup(target)
source.close();target.close()
workspace=read(AREA/'staged/payload-C.json')['registration']['workspace']
core=WSC(Store(OUT/'wsc.db',session_id='a3/sharedS2/C',workspace=workspace),access=lambda *args:True)
snapshot=core.capture()
material,offered=frontier(core,snapshot,None,original/'cold-public')
draft=read(original/'S2-generation/compiled-draft.json')
retained=draft.pop('retained_excerpt_keys',[])
assert not retained
selection=compile_draft(material,draft)
view=core.prepare(snapshot,selection,producer=POLICY['id'],limits=Limits(max_view_bytes=10000000))
with core.store.connect() as db:
    body=json.loads(db.execute('SELECT data FROM views WHERE id=?',(view,)).fetchone()[0])['body']
operation=core.stage(view,directory=OUT/'exports',archive_directory=OUT/'cold-objects',adapter=RecordedCodexCheckpointAdapter())
package=core.package(operation)
result=dict(original_draft_sha256=file_hash(original/'S2-generation/model-draft.json'),
    body_bytes=len(encode(body).encode()),body_parts={key:len(encode(value).encode()) for key,value in body.items()},
    rendered_bytes=len(encode(package['items']).encode()),source_count=len(body['sources']),excerpt_count=len(body.get('excerpts',[])),
    source_payload_bytes=sum(len(encode(row['payload']).encode()) for row in body['sources'] if row['kind']!='message'),
    registered_body_limit=POLICY['max_view_body_bytes'],registered_rendered_limit=POLICY['max_rendered_bytes'],
    scope='Offline measurement only; relaxed limit is not a changed study limit or accepted delivery',model_calls=0)
core.discard(operation)
assert file_hash(original/'wsc.db')==before
save(OUT/'result.json',result)
print(result)
