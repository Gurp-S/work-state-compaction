"""Replay the same model choices through lossless at-rest/wire projections."""
from pathlib import Path
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from wsc import WSC,Store
from wsc.contracts import Limits,encode
from wsc import events
from wsc.publication import check_evidence
from wsc.source_reference_view import MODE,hydrate
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from native_indexed_checkpoint import IndexedCheckpointAdapter,expand_working_state
from native_incremental_candidate import frontier,compile_draft,POLICY
from native_evidence import read,save,file_hash

AREA=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT=AREA/(sys.argv[1] if len(sys.argv)>1 else 'indexed-view-replay')
OUT.mkdir(exist_ok=False)
original=AREA/'arms/C/output'
source=sqlite3.connect('file:'+str(original/'wsc.db')+'?mode=ro',uri=True)
target=sqlite3.connect(OUT/'wsc.db');source.backup(target);source.close();target.close()
workspace=read(AREA/'staged/payload-C.json')['registration']['workspace']
core=WSC(Store(OUT/'wsc.db',session_id='a3/sharedS2/C',workspace=workspace),access=lambda *a:True)
snapshot=core.capture()
material,offered=frontier(core,snapshot,None,original/'cold-public')
draft=read(original/'S2-generation/compiled-draft.json');assert not draft.pop('retained_excerpt_keys',[])
selection=compile_draft(material,draft)
view=core.prepare(snapshot,selection,producer=POLICY['id'],limits=Limits(max_view_bytes=POLICY['max_view_body_bytes']),source_projection=MODE)
adapter=IndexedCheckpointAdapter()
operation=core.stage(view,directory=OUT/'exports',archive_directory=OUT/'cold-objects',adapter=adapter)
package=core.package(operation)
check_evidence(core,package)
with core.store.connect() as db:
    body=json.loads(db.execute('SELECT data FROM views WHERE id=?',(view,)).fetchone()[0])['body']
    source_rows=events.rows(db)
restored=hydrate(body,source_rows)
restored['excerpt_locators']=package['excerpt_evidence']
expected=RecordedCodexCheckpointAdapter().render(restored,source_rows,package['binding']['cut'],package['evidence'],
    source_index=package['source_index'],understanding_index=package['understanding_index'])
index=sum(row['kind']=='message' for row in body['sources'])
table=read(package['adapter']['projection_evidence']['file_path'])
expanded=expand_working_state(package['items'][index]['content'][0]['text'],table)
assert expanded==json.loads(expected[index]['content'][0]['text'])
assert package['items'][:index]==expected[:index] and package['items'][index+1:]==expected[index+1:]
rendered=len(encode(package['items']).encode())
save(OUT/'package.json',package)
result=dict(same_model_draft_sha256=file_hash(original/'S2-generation/model-draft.json'),
    original_measurement=read(AREA/'oversize-draft-analysis/result.json'),
    projected_body_bytes=len(encode(body).encode()),rendered_bytes=rendered,
    within_rendered_limit=rendered<=POLICY['max_rendered_bytes'],
    expanded_working_state_identical=True,other_native_items_identical=True,original_selection_unchanged=True,
    source_ids=len(selection.source_ids),excerpts=len(selection.excerpts),model_calls=0,
    scope='Offline compile/export only; no host install or continuation proof')
save(OUT/'result.json',result)
core.discard(operation)
print(result)
