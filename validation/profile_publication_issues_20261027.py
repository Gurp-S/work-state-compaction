"""Measure complete cold catalogs without silently dropping recovery sources."""
from pathlib import Path
import argparse,json,sqlite3,sys,time,tracemalloc
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Selection,Understanding
from wsc import understanding
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.resource_io import ResourceIO


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);report=dict(model_calls=0,scales=[],scope='Full recovery catalogs; not selected-only exports or model cost.')
    for n in (100,1000,10000):
        path=args.out/f'scale-{n}.db'
        with sqlite3.connect(args.source/f'scale-{n}.db') as original,sqlite3.connect(path) as copy:original.backup(copy)
        store=Store(path,session_id='s',workspace=str(args.source))
        with store.transaction() as db:
            for i in range(n):understanding.write(db,Understanding(f'version-{i}','observation',('result',),id='revision-series',expected_revision=i or None),producer='fixture',allowed_sources={'result'})
        core=WSC(store,access=lambda *a:True,query_policy='prefix_index_v1')
        view=core.prepare(core.capture(),Selection(understanding_refs=(f'revision-series@{n}',)),producer='fixture')
        for label,io in (('legacy',None),('bounded',ResourceIO())):
            core.resource_io=io
            for iteration in (1,2):
                tracemalloc.start();begin=time.perf_counter()
                op=core.stage(view,directory=args.out/f'{n}-{label}-exports',archive_directory=args.out/f'{n}-{label}-objects',adapter=CodexCheckpointAdapter())
                seconds=time.perf_counter()-begin;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
                package=core.package(op)
                records=json.loads(Path(package['understanding_index']).read_text(encoding='utf-8'))
                report['scales'].append(dict(events=n+2,understanding_versions=n+2,mode=label,iteration=iteration,
                    seconds=seconds,peak_python_bytes=peak,exported_sources=len(package['evidence']),exported_understandings=len(records),
                    selected_understandings=1,source_index_bytes=Path(package['source_index']).stat().st_size,
                    understanding_index_bytes=Path(package['understanding_index']).stat().st_size))
                core.discard(op)
    (args.out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
