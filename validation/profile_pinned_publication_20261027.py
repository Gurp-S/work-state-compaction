"""Re-use prior fixtures; measure only the new pinned publication path once."""
from pathlib import Path
import argparse,json,sqlite3,sys,time,tracemalloc
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Selection
from wsc.resource_io import ResourceIO
from wsc.adapters.codex import CodexCheckpointAdapter


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    report=dict(model_calls=0,baseline_report_sha256=sha256((args.source/'result.json').read_bytes()).hexdigest(),scales=[])
    for n in (100,1000,10000):
        path=args.out/f'scale-{n}.db'
        with sqlite3.connect(args.source/f'scale-{n}.db') as source,sqlite3.connect(path) as target:source.backup(target)
        with sqlite3.connect(path) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
        store=Store(path,session_id=binding['session_id'],workspace=binding['workspace']);io=ResourceIO()
        core=WSC(store,access=lambda *a:True,resource_io=io,query_policy='prefix_index_v1')
        view=core.prepare(core.capture(),Selection(understanding_refs=(f'revision-series@{n}',)),producer='fixture')
        tracemalloc.start();begin=time.perf_counter()
        op=core.stage(view,directory=args.out/f'{n}-exports',archive_directory=args.source/f'{n}-legacy-objects',adapter=CodexCheckpointAdapter())
        seconds=time.perf_counter()-begin;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        package=core.package(op)
        item=dict(events=n+2,seconds=seconds,peak_python_bytes=peak,object_bytes_read=io.bytes_read,exported_sources=len(package['evidence']))
        report['scales'].append(item);print(json.dumps(item),flush=True);core.discard(op)
        (args.out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
