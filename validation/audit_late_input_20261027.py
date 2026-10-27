"""Byte attribution and reversible metadata-table feasibility, no model use."""
from pathlib import Path
import argparse,json,sys,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash


def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def size(value):return len(packed(value).encode())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root
    source=root/'R01/C2-generation/request.json';request=read(source);events=request['material']['events']
    old=[(index,event) for index,event in enumerate(events) if event.get('text_in_frontier') is False]
    keys=sorted(old[0][1]);assert all(sorted(event)==keys for _,event in old)
    defaults={key:copy.deepcopy(old[0][1][key]) for key in keys if all(packed(event[key])==packed(old[0][1][key]) for _,event in old)}
    columns=[key for key in keys if key not in defaults]
    table=dict(schema='wsc.metadata-table-feasibility/1',count=len(events),defaults=defaults,columns=columns,
        rows=[[index,*[event[key] for key in columns]] for index,event in old],
        other=[[index,event] for index,event in enumerate(events) if event.get('text_in_frontier') is not False])
    restored=[None]*len(events)
    for row in table['rows']:restored[row[0]]={**copy.deepcopy(defaults),**dict(zip(columns,row[1:]))}
    for index,event in table['other']:restored[index]=event
    assert packed(restored)==packed(events)
    candidate=copy.deepcopy(request);candidate['material']['events']=table
    decoded=copy.deepcopy(candidate);decoded['material']['events']=restored;assert packed(decoded)==packed(request)
    report=dict(model_calls=0,source_sha256=file_hash(source),request_bytes=size(request),schema_bytes=size(read(root/'R01/C2-generation/schema.json')),
        material_field_bytes={key:size(value) for key,value in request['material'].items()},
        old_event_count=len(old),uniform_old_metadata_keys=list(defaults),table_columns=columns,
        feasibility_request_bytes=size(candidate),feasibility_roundtrip_exact=True,
        production_codec_implemented=False,model_quality_or_tokens_measured=False,
        scope='Byte equality feasibility only. No field removed, no semantic selection; changing model representation still needs implementation and actual QA.')
    save(root/'input-audit.json',report);save(root/'metadata-table-feasibility.json',table);print(json.dumps(report))


if __name__=='__main__':main()
