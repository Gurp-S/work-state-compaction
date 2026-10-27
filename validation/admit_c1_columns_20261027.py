"""Replay original first selection through homogeneous metadata columns."""
from pathlib import Path
from copy import deepcopy
import argparse,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation')]
from native_metadata_columns import project as metadata,restore as restore_metadata
from native_event_columns import project as events,restore as restore_events
from native_evidence import read,save,file_hash
from admit_metadata_columns_20261027 import compiled
from wsc.contracts import encode


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);begin=time.perf_counter();g=args.source/'R01/C1-generation';request=read(g/'request.json')
    intermediate,b1=metadata(request['material']);represented,b2=events(intermediate)
    decoded=restore_metadata(restore_events(represented,b2),b1)
    assert b2['applied'] and b1['paths'] and encode(decoded)==encode(request['material'])
    assert encode(compiled(request['material'],g,None))==encode(compiled(decoded,g,None))
    wire=deepcopy(request);wire['material']=represented
    save(args.out/'request.json',wire);save(args.out/'metadata-binding.json',b1);save(args.out/'events-binding.json',b2)
    result=dict(passed=True,model_calls=0,seconds=time.perf_counter()-begin,request_bytes_before=len(encode(request).encode()),request_bytes_after=len(encode(wire).encode()),
        events_before=len(encode(request['material']['events']).encode()),events_after=len(encode(represented['events']).encode()),
        roundtrip_exact=True,compiled_selection_exact=True,source_request_sha256=file_hash(g/'request.json'),source_schema_sha256=file_hash(g/'schema.json'),source_database_sha256=file_hash(args.source/'R01/state.db'),
        codecs_sha256={name:file_hash(ROOT/'experiments'/name) for name in ('native_event_columns.py','native_metadata_columns.py')},
        scope='Zero-model representation admission only. No new quality or Token saving claim.')
    save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
