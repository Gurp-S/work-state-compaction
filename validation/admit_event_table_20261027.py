"""Real completed draft replay through reversible input encoding, no model."""
from pathlib import Path
from dataclasses import asdict
import argparse,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_evidence import read,save,file_hash
from native_event_table import project,restore
from native_selection_wire import restore as restore_wire,normalize_draft
from native_span_handles import expand
from native_incremental_candidate import compile_draft
from native_incremental_compile import compile_choice
from wsc.contracts import encode


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    if not read(args.source/'audit.json')['passed']:raise ValueError('source_not_audited')
    generation=args.source/'R01/C2-generation';request=read(generation/'request.json');wire=request['material']
    represented,binding=project(wire);decoded=restore(represented,binding)
    assert encode(decoded)==encode(wire) and binding['applied']
    manifest=read(generation/'resource-manifest.json');bindings=read(generation/'wire-bindings.json')
    handles=read(generation/'span-handle-bindings.json');raw=read(generation/'model-draft.json')
    draft=expand(normalize_draft(raw,bindings),handles)
    assert encode(draft)==encode(read(generation/'compiled-draft.json'))
    previous=read(args.source/'R01/C1-continuation.json');selections=[]
    for material in (wire,decoded):
        restored=restore_wire(material,manifest,bindings)
        identities={event['id']:event['cold_source']['source_id'] for event in restored['events']}
        for event in restored['events']:
            # span_material exposes source aliases and exact text blocks. Core
            # compilation takes original identities and producer public text.
            event['id']=event['cold_source']['source_id']
            event['text']=''.join(span['text'] for span in event['spans']) if event['public_text_available'] else None
            if event['text'] is not None:assert len(event['text'])==event['public_text_characters']
        facts=restored.get('selection_facts',{})
        if 'source_records' in facts:facts['source_records']={identities[key]:value for key,value in facts['source_records'].items()}
        for record in restored.get('understandings',[]):record['sources']=[identities[key] for key in record['sources']]
        selections.append(compile_choice(restored,previous,draft,compile_draft))
    assert encode(asdict(selections[0]))==encode(asdict(selections[1]))
    result=dict(passed=True,model_calls=0,seconds=time.monotonic()-begin,roundtrip_exact=True,compiled_selection_exact=True,
        material_bytes_before=len(encode(wire).encode()),material_bytes_after=len(encode(represented).encode()),
        cold_events=binding['cold_events'],original_events=binding['original_events'],
        source_request_sha256=file_hash(generation/'request.json'),source_draft_sha256=file_hash(generation/'model-draft.json'),
        source_database_sha256=file_hash(args.source/'R01/state.db'),
        codec_sha256=file_hash(ROOT/'experiments/native_event_table.py'),scope='Representation/compilation only; not model answer or cost proof.')
    save(args.out/'binding.json',binding);save(args.out/'represented-material.json',represented);save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
