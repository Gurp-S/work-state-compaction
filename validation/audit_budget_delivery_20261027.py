"""Offline delivery costs in exact JSON bytes; no guessed Token conversion."""
from pathlib import Path
from copy import deepcopy
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_evidence import read,save
from wsc.contracts import encode,digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--c1',type=Path,required=True);p.add_argument('--c2',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);cases=[]
    for root in (args.c1,args.c2):
        request=read(root/'request.json');schema=read(root/'schema.json');table=request['material']['selection_facts']['source_record_table'];wire=deepcopy(request)
        wire['material']['selection_facts']['source_record_table']=dict(format='hypothetical.budget_reference/1',sha256=digest(table))
        whole=len(encode(request).encode());deferred=len(encode(wire).encode());size=len(encode(table).encode())
        cases.append(dict(generation=str(root),request_bytes=whole,table_bytes=size,hypothetical_deferred_request_bytes=deferred,first_request_saving_bytes=whole-deferred,
            extra_response_known_input_floor_bytes=deferred+len(encode(schema).encode()),token_conversion=None,
            limitation='Whole-table lookup on a separate first response then returns the original table to attention; this adds a request, not a permanent per-turn table saving. Coalescing/subset retrieval may behave differently.'))
    trace=read(args.c2.parent/'source-tool-trace.json');table_size=cases[1]['table_bytes']
    piggyback=[dict(operation=x['arguments']['operation'],original_output_bytes=len(encode(x['output']).encode()),
        with_plain_table_lower_bound_bytes=len(encode(x['output']).encode())+table_size,
        max_return_bytes=16384,fits_even_without_wrapper=len(encode(x['output']).encode())+table_size<=16384) for x in trace]
    result=dict(passed=True,model_calls=0,cases=cases,piggyback_observations=piggyback,
        decision='No live standalone budget tool in this revision. Full-table deferral may add model turns; piggyback needs bounded-output/fallback and permission design.',
        scope='Exact hypothetical JSON bytes only; not measured model Token, latency, behavior or proof that every on-demand design is inferior.')
    save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
