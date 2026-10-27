"""Replay accepted drafts through optional column representation, zero models."""
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
import argparse,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_evidence import read,save,file_hash
from native_metadata_columns import project,restore
from native_event_table import restore as restore_events
from native_selection_wire import restore as restore_wire,normalize_draft
from native_span_handles import expand
from native_incremental_candidate import compile_draft
from native_incremental_compile import compile_choice
from wsc.contracts import encode


def compiled(wire,generation,previous):
    material=restore_wire(wire,read(generation/'resource-manifest.json'),read(generation/'wire-bindings.json'))
    draft=expand(normalize_draft(read(generation/'model-draft.json'),read(generation/'wire-bindings.json')),read(generation/'span-handle-bindings.json'))
    assert encode(draft)==encode(read(generation/'compiled-draft.json'))
    identities={event['id']:event['cold_source']['source_id'] for event in material['events']}
    for event in material['events']:
        event['id']=event['cold_source']['source_id']
        event['text']=''.join(span['text'] for span in event['spans']) if event['public_text_available'] else None
        if event['text'] is not None:assert len(event['text'])==event['public_text_characters']
    facts=material.get('selection_facts',{})
    if 'source_records' in facts:facts['source_records']={identities[key]:v for key,v in facts['source_records'].items()}
    for record in material.get('understandings',[]):record['sources']=[identities[key] for key in record['sources']]
    return asdict(compile_choice(material,previous,draft,compile_draft))


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--candidates',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);begin=time.perf_counter();before=file_hash(args.source/'R01/state.db');previous=read(args.source/'R01/C1-continuation.json');checks=[]
    for number,candidate in enumerate(args.candidates,1):
        assert read(candidate/'result.json')['status']=='completed' and read(candidate/'source-tool-audit.json')['passed']
        generation=candidate/'generation';request=read(generation/'request.json');original=request['material']
        represented,binding=project(original);decoded=restore(represented,binding)
        assert encode(decoded)==encode(original) and len(binding['paths'])==2
        first=restore_events(original,read(generation/'event-table-binding.json'));second=restore_events(decoded,read(generation/'event-table-binding.json'))
        assert encode(compiled(first,generation,previous))==encode(compiled(second,generation,previous))
        new_request=deepcopy(request);new_request['material']=represented
        save(args.out/f'R{number:02d}-request.json',new_request);save(args.out/f'R{number:02d}-binding.json',binding)
        checks.append(dict(candidate=str(candidate),request_bytes_before=len(encode(request).encode()),request_bytes_after=len(encode(new_request).encode()),
            event_rows_bytes_before=len(encode(original['events']['rows']).encode()),event_rows_bytes_after=len(encode(represented['events']['rows']).encode()),
            source_budget_rows_bytes_before=len(encode(original['selection_facts']['source_record_table']['rows']).encode()),source_budget_rows_bytes_after=len(encode(represented['selection_facts']['source_record_table']['rows']).encode()),
            source_request_sha256=file_hash(generation/'request.json'),source_draft_sha256=file_hash(generation/'model-draft.json'),exact_roundtrip=True,exact_compiled_selection=True))
    assert before==file_hash(args.source/'R01/state.db')
    result=dict(passed=True,model_calls=0,seconds=time.perf_counter()-begin,checks=checks,source_database_sha256=before,source_unchanged=True,
        codec_sha256=file_hash(ROOT/'experiments/native_metadata_columns.py'),default_enabled=False,
        scope='Exact representation and accepted draft compilation only; bytes are not Tokens and new model quality/latency unmeasured.')
    save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
