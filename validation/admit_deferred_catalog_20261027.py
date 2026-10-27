"""Actual accepted C2 replay: full restoration, compilation and source tool ABI."""
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
from contextlib import closing
import argparse,json,sqlite3,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation')]
from native_event_table import restore as restore_events
from native_deferred_catalog import project,restore
from native_catalog_tool import CatalogAccess,CatalogToolHandler
from native_evidence import read,save,file_hash
from admit_metadata_columns_20261027 import compiled
from wsc import WSC,Store
from wsc.contracts import encode


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    source=args.source/'R01';g=source/'C2-generation';request=read(g/'request.json');raw=restore_events(request['material'],read(g/'event-table-binding.json'))
    assert read(args.source/'audit.json')['passed'] and read(args.source/'C1-equivalence-audit.json')['passed']
    before=file_hash(source/'state.db');args.out.mkdir(parents=True,exist_ok=False);begin=time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'state.db'
        with closing(sqlite3.connect(source/'state.db')) as a,closing(sqlite3.connect(path)) as b:a.backup(b)
        with closing(sqlite3.connect(path)) as db:
            binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
            assert db.execute('SELECT count(*) FROM understandings').fetchone()[0]==0
        core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,query_policy='prefix_index_v1')
        snapshot=core.capture();handler=CatalogToolHandler(CatalogAccess(core.store,snapshot,access=core.access))
        represented,payload,private=handler.project_material(raw);assert private['applied']
        response=handler.handle(dict(id='catalog',method='item/tool/call',params=dict(threadId='t',turnId='u',callId='catalog',tool='WSCSource',arguments={'operation':'catalog'})),thread_id='t',turn_id='u')
        assert response['result']['success'];value=json.loads(response['result']['contentItems'][0]['text'])
        decoded=restore(represented,value['catalog'],private);assert encode(decoded)==encode(raw)
        previous=read(source/'C1-continuation.json');assert encode(compiled(raw,g,previous))==encode(compiled(decoded,g,previous))
        # With no catalog call, old read/find output bytes and all counters stay
        # identical. Run the exact accepted ordered trace against a fresh reader.
        replay=CatalogToolHandler(CatalogAccess(core.store,snapshot,access=core.access));replay.project_material(raw)
        trace=read(source/'C2-tool-trace.json')
        for i,call in enumerate(trace):
            event=dict(id=i,method='item/tool/call',params=dict(threadId=call['thread_id'],turnId=call['turn_id'],callId=call['call_id'],tool='WSCSource',arguments=call['arguments']))
            out=replay.handle(event,thread_id=call['thread_id'],turn_id=call['turn_id'])
            assert encode(json.loads(out['result']['contentItems'][0]['text']))==encode(call['output'])
    assert before==file_hash(source/'state.db')
    new_request=deepcopy(request);new_request['material']=represented
    save(args.out/'request.json',new_request);save(args.out/'catalog.json',payload);save(args.out/'binding.json',private);save(args.out/'catalog-result.json',value)
    result=dict(passed=True,model_calls=0,seconds=time.perf_counter()-begin,source=str(args.source),source_database_sha256=before,
        baseline_request_bytes=len(encode(request).encode()),raw_before_rows_bytes=len(encode({**request,'material':raw}).encode()),request_bytes_after=len(encode(new_request).encode()),
        catalog_result_bytes=len(encode(value).encode()),single_result_limit=handler.reader.limits.max_return_bytes,
        snapshot_sources=len(handler.reader.order),catalog_calls=handler.reader.calls,catalog_live_rows_verified=handler.reader.rows_verified,
        exact_restore=True,compiled_selection_exact=True,source_trace_replay_exact=True,replayed_calls=len(trace),
        codecs_sha256={n:file_hash(ROOT/'experiments'/n) for n in ('native_deferred_catalog.py','native_catalog_tool.py','native_source_tool.py','native_incremental_generation.py')},
        scope='New system resource tradeoff: catalog consumes one of the same eight calls. Snapshot metadata is not current storage validation; model behavior and costs unmeasured.')
    save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
