"""Alternating paired read/verify profile; unchanged files and checks, no LLM."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys,time,statistics
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wsc.resource_io import ResourceIO
from wsc.bound_windows_io import BoundWindowsIO


def main():
    parser=argparse.ArgumentParser()
    for name in ('package','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    package=json.loads(args.package.read_text());paths={}
    for record in package['evidence'].values():
        for key,checksum in [('file_path','sha256'),('readable_path','readable_sha256')]:
            if key in record:paths[record[key]]=record[checksum]
    # Warm both against exactly the same immutable paths before paired samples.
    for kind in (ResourceIO,BoundWindowsIO):
        io=kind()
        for path,expected in paths.items():assert io.digest(path)==expected
    begin=time.perf_counter();pairs=[]
    for trial in range(5):
        row={}
        for name,kind in ([('original',ResourceIO),('bound',BoundWindowsIO)] if trial%2==0 else [('bound',BoundWindowsIO),('original',ResourceIO)]):
            io=kind();start=time.perf_counter()
            values={path:io.digest(path) for path in paths}
            row[name]=dict(seconds=time.perf_counter()-start,bytes_read=io.bytes_read)
            assert values==paths
        assert row['original']['bytes_read']==row['bound']['bytes_read'];pairs.append(row)
    result=dict(model_calls=0,seconds=time.perf_counter()-begin,files=len(paths),pairs=pairs,
        original_median=statistics.median(r['original']['seconds'] for r in pairs),bound_median=statistics.median(r['bound']['seconds'] for r in pairs),
        scope='Warm OS-cache local file verification, alternating five pairs. Identical hashes/bytes/flags/checks; not model or full-stage speed proof.')
    with (args.out/'result.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result))


if __name__=='__main__':main()
