"""Actual prepared-body byte assertions and source-call diagnostics; no models."""
from pathlib import Path
import argparse,json,sqlite3,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Selection,Limits
from wsc.contracts import Event,encode,WSCError
from wsc.source_reference_view import MODE
from wsc.selection_facts import describe as legacy
from wsc.projected_selection_facts import describe,admit
from wsc.view_budget import admit_generation
from native_evidence import save,read,file_hash


def rejected(function,*args):
    try:function(*args)
    except WSCError as error:return str(error)
    return None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--trace',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);begin=time.perf_counter();cases=[]
    with tempfile.TemporaryDirectory() as tmp:
        for control in (False,True):
            folder=Path(tmp)/str(control);folder.mkdir()
            core=WSC(Store(folder/'s.db',session_id='s',workspace=str(folder)),access=lambda *a:True)
            core.ingest([Event('u','message',{'role':'user'},role='user',text='constraint'),Event('e','observation',{'large':'x'*200000},text='public receipt',control=control)])
            snap=core.capture();old=legacy(snap.events,1000);new=describe(snap.events,1000)
            view=core.prepare(snap,Selection(),producer='fixture',source_projection=MODE,limits=Limits(max_view_bytes=1000))
            with core.store.connect() as db:body=json.loads(db.execute('SELECT data FROM views WHERE id=?',(view,)).fetchone()[0])['body']
            actual=len(encode(body).encode());assert actual==new['mandatory_empty_view_bytes']
            assert rejected(admit,snap.events,1000) is None
            if control:assert rejected(admit_generation,snap.events,1000)=='mandatory_view_byte_budget_exhausted'
            cases.append(dict(explicit_control=control,old_empty_bytes=old['mandatory_empty_view_bytes'],new_empty_bytes=new['mandatory_empty_view_bytes'],actual_empty_bytes=actual,
                old_observation_bytes=old['source_records']['e']['serialized_record_bytes'],new_observation_bytes=new['source_records']['e']['serialized_record_bytes'],old_admission_error=rejected(admit_generation,snap.events,1000),new_admission_error=None))
    before=file_hash(args.source)
    with sqlite3.connect(args.source) as db:prefix=[dict(seq=seq,**json.loads(data)) for seq,data in db.execute('SELECT seq,data FROM events ORDER BY seq')]
    actual_case=dict(events=len(prefix),non_messages=sum(r['kind']!='message' for r in prefix),old_empty_bytes=legacy(prefix,131072)['mandatory_empty_view_bytes'],new_empty_bytes=describe(prefix,131072)['mandatory_empty_view_bytes'])
    assert before==file_hash(args.source)
    calls=read(args.trace);finds=[entry for call in calls if call['arguments']['operation']=='find' for entry in call['output']['matches']];extensions=[]
    for call in calls:
        if call['arguments']['operation']!='read':continue
        output=call['output']
        for found in finds:
            if output.get('source')==found['source']:
                assert output['text'][found['start']:found['end']]==found['text']
                extensions.append(dict(source=found['source'],find_range=[found['start'],found['end']],read_range=[output['offset'],output['end']],
                    added_characters=len(output['text'])-len(found['text']),read_complete=output['complete'],read_has_full_text_sha256='full_text_sha256' in output))
    result=dict(passed=True,model_calls=0,seconds=time.perf_counter()-begin,cases=cases,actual_late_case=actual_case,find_then_read=extensions,source_unchanged=True,
        limitations=['No claim about internal reasoning or why the model chose these calls.','find snippets and full read have different completeness evidence; engine cannot suppress them as duplicate semantic decisions.','Projection-aware accounting fixes facts, not a demonstrated latency cause or semantic-selection optimization.'])
    save(args.out/'result.json',result);print(result)


if __name__=='__main__':main()
