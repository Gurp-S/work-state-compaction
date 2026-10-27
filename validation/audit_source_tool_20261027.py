"""Offline exact source/tool-result audit; no models or semantic judge."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,file_hash,state
from native_rollout_snapshot import capture_rollout
from blackbox_recovery_case import decoded_objects
from wsc.contracts import encode,digest
from wsc.evidence import source_row


def audit(root,*,selection_only=False,decode_json_strings=False):
    trace=read(root/'source-tool-trace.json');snap=capture_rollout(root/'selection/rollout.jsonl')
    assert snap.metadata['parse_complete']
    persisted={}
    for number,row in enumerate(snap.rows,1):
        payload=row.get('payload',{})
        if row['type']=='response_item' and payload.get('type') in ('function_call_output','custom_tool_call_output'):
            decoder=decoded_objects
            if decode_json_strings:
                from structured_tool_outputs import decoded_transport_objects
                decoder=decoded_transport_objects
            for value in decoder(payload.get('output')):
                persisted.setdefault(encode(value),[]).append(number)
    checks=[]
    with sqlite3.connect(root/'state.db') as db:
        db.row_factory=sqlite3.Row
        for call in trace:
            output=call['output'];hits=persisted.get(encode(output),[]);assert hits
            if call['arguments']['operation']=='find':entries=output['matches']
            else:entries=[output]
            for entry in entries:
                row=source_row(db,entry['original_source_id']);text=row['text']
                assert digest(row)==entry['source_record_sha256']
                assert entry['source']=='s'+str(row['seq']) and entry['seq']==row['seq']
                for key in ('kind','role','observed_at'):assert entry[key]==row[key]
                start=entry.get('offset',entry.get('start'));end=entry['end']
                assert text[start:end]==entry['text']
                assert sha256(entry['text'].encode()).hexdigest()==entry['text_sha256']
                if call['arguments']['operation']=='find':
                    assert text[entry['match_start']:entry['match_end']]==call['arguments']['literal']
                else:assert sha256(text.encode()).hexdigest()==entry['full_text_sha256']
            checks.append(dict(call_id=call['call_id'],operation=call['arguments']['operation'],
                source_count=len(entries),exact_native_output_lines=sorted(set(hits))))
    result=read(root/'result.json')
    if selection_only:
        phase=read(root/'selection/phase-outcome.json')
        assert phase['completed'] and phase['failure'] is None and phase['usage_complete']
    else:assert result['status']=='completed' and not result['ledger']['study']['uncertain']
    assert all(item['empty_confirmed'] for item in result['cleanup'].values())
    bootstrap=capture_rollout(root/'selector-bootstrap.jsonl')
    tools=[tool.get('name') for r in bootstrap.rows if r['type']=='session_meta' for tool in r['payload'].get('dynamic_tools',[])]
    assert 'WSCSource' in tools
    return dict(passed=True,model_calls=0,call_checks=checks,registered_dynamic_tools=tools,
        scores=(result.get('scores') or {}).get('counts'),selection_only=selection_only,
        overall_status=result['status'],known_usage=phase['receipts']['all_usage'] if selection_only else result['ledger']['study'],
        bootstrap_canonical_bytes=sum(len(encode(item).encode()) for item in state(bootstrap.rows)),
        evidence_sha256={name:file_hash(root/name) for name in ['source-tool-trace.json','result.json','selection/rollout.jsonl','selector-bootstrap.jsonl']},
        scope='Exact source bytes/ranges/hashes and persisted model tool outputs; no inference about semantic entailment or universal task quality.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--selection-only',action='store_true');args=parser.parse_args()
    result=audit(args.root,selection_only=args.selection_only);save(args.root/('source-tool-selection-audit.json' if args.selection_only else 'source-tool-audit.json'),result)
    print(json.dumps({k:result[k] for k in ('passed','model_calls','scores','bootstrap_canonical_bytes')}))
