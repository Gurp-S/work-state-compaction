"""Local complexity/peak-memory measurements; never dispatch a model."""
from pathlib import Path
import argparse,json,sys,time,tracemalloc,statistics
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wsc import WSC,Store,Understanding
from wsc.contracts import Event,encode
from wsc import events
from wsc.resource_io import ResourceIO


def measured(function):
    digest=events.digest
    with patch('wsc.events.digest',wraps=digest) as calls:
        begin=time.perf_counter();function();seconds=time.perf_counter()-begin
    return dict(seconds=seconds,source_records_hashed=calls.call_count)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);report=dict(model_calls=0,prefix_cut=2,scales=[],memory=[])
    for n in (100,1000,10000):
        store=Store(args.out/f'scale-{n}.db',session_id='s',workspace=str(args.out))
        old=WSC(store,access=lambda *a:True);fast=WSC(store,access=lambda *a:True,query_policy='prefix_index_v1')
        old.ingest([Event('call','call',{},call_id='c'),Event('result','result',{},call_id='c'),
            *[Event(f'n-{i}','observation',dict(log='x'*128),text='x'*128) for i in range(n)]])
        with store.transaction() as db:
            for i in range(n):events.presented(db,f'p-{i}',('result',),receiver='fixture')
        before=measured(lambda:old.capture(cut=2));cold=measured(lambda:fast.capture(cut=2))
        warm=[measured(lambda:fast.capture(cut=2)) for _ in range(3)]
        remember_old=measured(lambda:old.remember(Understanding('old','observation',('result',)),producer='fixture'))
        remember_fast=measured(lambda:fast.remember(Understanding('fast','observation',('result',)),producer='fixture'))
        report['scales'].append(dict(noise_events=n,presentation_receipts=n,before=before,index_build=cold,
            warm=warm,remember_before=remember_old,remember_after=remember_fast))
    for size in (1024*1024,8*1024*1024):
        payload=b'x'*size;path=args.out/f'memory-{size}.bin';path.write_bytes(payload)
        peaks={}
        for name,operation in [('legacy_compare',lambda:path.read_bytes()==payload),
                ('bounded_compare',lambda:ResourceIO().equal(path,payload))]:
            tracemalloc.start();begin=time.perf_counter();assert operation()
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            peaks[name]=dict(peak_extra_python_bytes=peak,seconds=time.perf_counter()-begin)
        report['memory'].append(dict(payload_bytes=size,**peaks))
    (args.out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
