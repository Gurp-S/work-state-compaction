"""Reuse all three paid drafts; lossless projection and compiled-selection A/B."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_selection_wire import project,restore,normalize_draft
from native_incremental_generation import output_schema
from native_incremental_candidate import compile_draft
from native_span_handles import expand
from wsc import WSC,Store
from wsc.contracts import encode,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);rows=[]
    for r in (1,2,3):
        source=args.source/f'R{r:02d}';folder=args.out/f'R{r:02d}';folder.mkdir()
        request=json.loads((source/'generation/request.json').read_text());old=request['material']
        wire,manifest,bindings=project(old,folder/'resource-manifest.json')
        assert restore(wire,manifest,bindings)==old
        schema=output_schema(old,source_aliases_only=True)
        new={**request,'material':wire};newdraft=normalize_draft(json.loads((source/'generation/model-draft.json').read_text()),bindings)
        newdraft=expand(newdraft,json.loads((source/'generation/span-handle-bindings.json').read_text()))
        olddraft=json.loads((source/'generation/compiled-draft.json').read_text())
        olddraft.pop('retained_excerpt_keys',None);newdraft.pop('retained_excerpt_keys',None)
        dbpath=folder/'state.db'
        with closing(sqlite3.connect(source/'state.db')) as original,closing(sqlite3.connect(dbpath)) as copy:original.backup(copy)
        with closing(sqlite3.connect(dbpath)) as db:bound=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
        core=WSC(Store(dbpath,session_id=bound['session_id'],workspace=bound['workspace']),access=lambda *a:True,query_policy='prefix_index_v1')
        material=core.material(core.capture())
        assert compile_draft(material,olddraft)==compile_draft(material,newdraft)
        oldschema=json.loads((source/'generation/schema.json').read_text())
        item=dict(repetition=r,original_request_bytes=len(encode(request).encode()),new_request_bytes=len(encode(new).encode()),
            original_schema_bytes=len(encode(oldschema).encode()),new_schema_bytes=len(encode(schema).encode()),
            manifest_bytes=len(encode(manifest).encode()),roundtrip_exact=True,compiled_selection_equal=True,
            public_spans=sum(len(e['spans']) for e in wire['events']),source_records=len(wire['events']))
        rows.append(item);(folder/'request.json').write_text(encode(new),encoding='utf-8');(folder/'schema.json').write_text(encode(schema),encoding='utf-8')
    (args.out/'result.json').write_text(json.dumps(dict(model_calls=0,rows=rows,scope='Lossless representation and same-draft compilation only; actual model token/quality benefit unmeasured.'),indent=2),encoding='utf-8')
    print(json.dumps(rows))


if __name__=='__main__':main()
