"""Paired zero-model search profile over existing frozen probe fixtures."""
from pathlib import Path
import argparse,json,sys,time,tracemalloc,sqlite3
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store
from wsc.source_access import SnapshotSourceAccess
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from probe_late_source_access_20261027 import search


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False);rows=[];begin=time.perf_counter()
    for case in read(args.source/'result.json')['rows']:
        area=args.source/f"N{case['size']}-at{case['target_seq']}";path=area/'state.db'
        before=sha256(path.read_bytes()).hexdigest()
        with sqlite3.connect(path) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
        core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True)
        # Snapshot cost is separately visible; both readers receive this same
        # already-captured object. The new catalog is not a cheap-snapshot claim.
        start=time.perf_counter();snapshot=core.capture();snapshot_seconds=time.perf_counter()-start
        row=dict(size=case['size'],target_seq=case['target_seq'],snapshot_seconds=snapshot_seconds)
        for label,kind in [('legacy',SnapshotSourceAccess),('snapshot',SnapshotLiteralAccess)]:
            tracemalloc.start();start=time.perf_counter();reader=kind(core.store,snapshot,access=core.access)
            build_seconds=time.perf_counter()-start;start=time.perf_counter();result=search(reader,'receipt:fixed-probe-target')
            query_seconds=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            hits=[match for page in result['pages'] for match in page['matches']]
            if hits:assert hits[0]['source']=='s'+str(case['target_seq']) and hits[0]['text']=='receipt:fixed-probe-target historical-value-7f4c'
            row[label]=dict(found=result['found'],complete=result['complete'],calls=len(result['pages']),
                rows_verified=reader.rows_verified,text_bytes_examined=reader.text_bytes_examined,
                build_seconds=build_seconds,query_seconds=query_seconds,build_and_search_python_peak_bytes=peak,
                physical_disk_bytes=None)
            (args.out/(area.name+'-'+label+'.json')).write_text(json.dumps(result,indent=2))
        assert sha256(path.read_bytes()).hexdigest()==before
        row['source_db_sha256']=before;row['source_unchanged']=True
        rows.append(row)
    result=dict(model_calls=0,rows=rows,seconds=time.perf_counter()-begin,
        resource_scope='One instrumented local run, constructor and search Python allocations; excludes existing snapshot/process peak and does not prove statistical latency or model answer quality.')
    (args.out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


def read(path):return json.loads(path.read_text())
if __name__=='__main__':main()
