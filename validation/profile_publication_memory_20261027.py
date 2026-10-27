"""Fresh-process paired serialization measurement; no model calls."""
from pathlib import Path
import argparse,json,sqlite3,sys,time,tracemalloc,subprocess,ctypes
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Selection
from wsc.resource_io import ResourceIO
from wsc.adapters.codex import CodexCheckpointAdapter


def memory():
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_=[('cb',w.DWORD),('PageFaultCount',w.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    api=ctypes.WinDLL('psapi',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=w.HANDLE
    api.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD]
    result=Counters();result.cb=ctypes.sizeof(result)
    if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(result),result.cb):raise ctypes.WinError(ctypes.get_last_error())
    return {name:getattr(result,name) for name in ('PeakWorkingSetSize','WorkingSetSize','PeakPagefileUsage')}


def worker(args):
    path=args.out/(args.mode+'.db')
    with closing(sqlite3.connect(args.source/f'scale-{args.size}.db')) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    store=Store(path,session_id=binding['session_id'],workspace=binding['workspace'])
    core=WSC(store,access=lambda *a:True,resource_io=ResourceIO(),query_policy='prefix_index_v1',
        publication_policy='bounded_catalog_v1' if args.mode=='bounded' else None)
    view=core.prepare(core.capture(),Selection(understanding_refs=(f'revision-series@{args.size}',)),producer='fixture')
    before=memory();tracemalloc.start();begin=time.perf_counter()
    op=core.stage(view,directory=args.out/'exports',archive_directory=args.source/f'{args.size}-legacy-objects',adapter=CodexCheckpointAdapter())
    elapsed=time.perf_counter()-begin;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop();after_stage=memory()
    begin=time.perf_counter();package=core.package(op);package_seconds=time.perf_counter()-begin;after_package=memory()
    result=dict(mode=args.mode,events=args.size+2,seconds=elapsed,package_seconds=package_seconds,peak_python_bytes=peak,
        before=before,after_stage=after_stage,after_package=after_package,exported_sources=len(package['evidence']),
        source_index_bytes=Path(package['source_index']).stat().st_size,
        understanding_index_bytes=Path(package['understanding_index']).stat().st_size,model_calls=0)
    core.discard(op)
    (args.out/(args.mode+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--size',type=int,choices=[100,1000,10000],default=10000)
    parser.add_argument('--mode',choices=['pinned','bounded']);args=parser.parse_args()
    if args.mode:return worker(args)
    args.out.mkdir(parents=True,exist_ok=False)
    for mode in ('pinned','bounded'):
        subprocess.run([sys.executable,'-B','-X','utf8',__file__,'--source',str(args.source),'--out',str(args.out),'--mode',mode,'--size',str(args.size)],check=True)
    result=dict(scope='One fresh process per mode; full identical recovery catalogs; not a statistical performance claim.',
        model_calls=0,results=[json.loads((args.out/(mode+'.json')).read_text()) for mode in ('pinned','bounded')])
    (args.out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
