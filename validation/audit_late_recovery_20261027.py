"""Independent exact scoring, source-return and receipt audit; no models."""
from pathlib import Path
from contextlib import closing
import argparse,json,sys,sqlite3
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from late_recovery_case import build
from blackbox import score_answer
from blackbox_recovery_case import decoded_objects
from native_evidence import read,save,file_hash
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from wsc.evidence import source_row
from wsc.contracts import digest,encode


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--decode-json-strings',action='store_true');parser.add_argument('--arm');args=parser.parse_args()
    root=args.root;cell=root/'R01';public,oracle,target=build()
    assert read(root/'dataset.public.json')==public and read(root/'oracle.private.json')==oracle
    result=read(root/'result.json');assert result['status']=='completed' and not result['ledger']['study']['uncertain']
    assert all(c['empty_confirmed'] for c in result['cleanup'].values()) and read(root/'bootstrap-cleanup.json')['empty_confirmed']
    phase_names=['C1-selection','C2-selection','wsc-probe'];phases=[read(cell/name/'phase-outcome.json') for name in phase_names]
    receipts={}
    for name,phase in zip(phase_names,phases):
        assert phase['completed'] and phase['failure'] is None and phase['usage_complete']
        if name!='wsc-probe':
            index=1 if name.startswith('C1') else 2
            proof,request=verify_transcript(capture_rollout(cell/name/'rollout.jsonl'),phase)
            assert proof==read(cell/f'C{index}-generation/request-binding.json')
            if index==2:
                assert target['nonce'] not in encode(request)
                assert target['nonce'] not in encode(read(cell/'C2-generation/schema.json'))
        for receipt in phase['receipts']['response_receipts']:
            assert receipt['response_id'] not in receipts;receipts[receipt['response_id']]=receipt['usage']
    usage=result['ledger']['arms'][args.arm] if args.arm else result['ledger']['study']
    assert sum(r['total_tokens'] for r in receipts.values())==usage['tokens']
    assert len(receipts)==usage['responses']
    rows=capture_rollout(cell/'C2-selection/rollout.jsonl').rows;objects=set()
    for row in rows:
        payload=row.get('payload',{})
        if row['type']=='response_item' and payload.get('type') in ('function_call_output','custom_tool_call_output'):
            decoder=decoded_objects
            if args.decode_json_strings:
                from structured_tool_outputs import decoded_transport_objects
                decoder=decoded_transport_objects
            objects.update(encode(obj) for obj in decoder(payload.get('output')))
    recovered=False;trace=read(cell/'C2-tool-trace.json')
    with closing(sqlite3.connect(cell/'state.db')) as db:
        db.row_factory=sqlite3.Row
        for call in trace:
            assert encode(call['output']) in objects
            hits=call['output'].get('matches',[]) if call['arguments']['operation']=='find' else [call['output']]
            for hit in hits:
                source=source_row(db,hit['original_source_id']);assert digest(source)==hit['source_record_sha256']
                assert source['text'][hit.get('start',hit.get('offset')):hit['end']]==hit['text']
                if source['seq']==540 and target['nonce'] in hit['text']:
                    assert json.loads(source['text'])==target;recovered=True
    assert recovered
    score=score_answer(phases[-1]['finals'][0]['text'],oracle);assert score==result['score']
    audit=dict(passed=True,model_calls=0,score=score['counts'],known_tokens=usage['tokens'],
        responses=len(receipts),second_selector_request_and_schema_without_nonce=True,
        target_recovered_in_exact_native_tool_result=True,target_seq=540,old_sources=641,source_tool_calls=len(trace),
        phases={name:dict(tokens=p['receipts']['all_usage']['total_tokens'],responses=p['receipts']['response_count'],seconds=p['seconds']) for name,p in zip(phase_names,phases)},
        evidence_sha256={str(p.relative_to(root)):file_hash(p) for p in [root/'result.json',root/'dataset.public.json',cell/'C2-tool-trace.json',cell/'C2-selection/rollout.jsonl',cell/'state.db']},
        scope='Single C-only qualification with two real selections and exact QA; no native B compaction, paired superiority or hidden-summary claim.')
    save(root/'audit.json',audit);print(json.dumps(audit))


if __name__=='__main__':main()
