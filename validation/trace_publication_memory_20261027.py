"""Line-boundary allocation diagnosis on an isolated copy of existing fixtures."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3,sys,tracemalloc,time,linecache
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Selection
from wsc.resource_io import ResourceIO
from wsc.adapters.codex import CodexCheckpointAdapter


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);path=args.out/'diagnostic.db'
    with closing(sqlite3.connect(args.source/'scale-10000.db')) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,resource_io=ResourceIO(),query_policy='prefix_index_v1')
    view=core.prepare(core.capture(),Selection(understanding_refs=('revision-series@10000',)),producer='fixture')
    rows=[];previous=None;filename=str(ROOT/'src/wsc/publication.py')
    def trace(frame,event,arg):
        nonlocal previous
        if frame.f_code.co_filename!=filename:return None
        if frame.f_code.co_name!='stage':return None
        if event in ('line','return'):
            current,peak=tracemalloc.get_traced_memory()
            if previous is not None:rows.append(dict(line=previous,current=current,peak=peak,source=linecache.getline(filename,previous).strip()))
            previous=frame.f_lineno;tracemalloc.reset_peak()
        return trace
    tracemalloc.start();sys.settrace(trace);begin=time.perf_counter()
    try:op=core.stage(view,directory=args.out/'exports',archive_directory=args.source/'10000-legacy-objects',adapter=CodexCheckpointAdapter())
    finally:sys.settrace(None);tracemalloc.stop()
    result=dict(model_calls=0,scope='Traced diagnosis; timing is not comparable with untraced measurements.',seconds=time.perf_counter()-begin,lines=rows)
    (args.out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    core.discard(op);print(json.dumps(sorted(rows,key=lambda r:r['peak'],reverse=True)[:8]),flush=True)


if __name__=='__main__':main()
