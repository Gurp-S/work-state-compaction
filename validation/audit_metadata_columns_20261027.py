"""Audit actual column candidate without a model judge or native summary access."""
from pathlib import Path
from copy import deepcopy
import sys,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from native_evidence import read,save,file_hash
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from native_metadata_columns import restore
from audit_source_tool_20261027 import audit
from wsc.contracts import encode


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);args=p.parse_args()
    candidate=args.root/'candidate';generation=candidate/'generation';old=args.baseline/'generation'
    request=read(generation/'request.json');before=read(old/'request.json');decoded=deepcopy(request)
    decoded['material']=restore(decoded['material'],read(generation/'metadata-column-binding.json'))
    for r in (decoded,before):
        for key in ('path','sha256'):r['material']['cold_source_manifest'].pop(key)
    assert encode(decoded)==encode(before)
    assert encode(read(generation/'schema.json'))==encode(read(old/'schema.json'))
    manifests=[read(path/'resource-manifest.json')['cold_sources'] for path in (old,generation)]
    assert list(manifests[0])==list(manifests[1])
    for key in manifests[0]:
        a,b=manifests[0][key],manifests[1][key]
        assert encode({k:v for k,v in a.items() if k!='path'})==encode({k:v for k,v in b.items() if k!='path'})
        assert file_hash(a['path'])==file_hash(b['path'])==a['sha256']
    phase=read(candidate/'selection/phase-outcome.json');proof,submitted=verify_transcript(capture_rollout(candidate/'selection/rollout.jsonl'),phase)
    assert encode(submitted)==encode(request) and proof==read(generation/'request-binding.json')
    result=read(args.root/'result.json');assert result['status']=='completed' and not result['ledger']['inflight'] and not result['ledger']['study']['uncertain']
    tool=audit(candidate,decode_json_strings=True);assert tool['passed'];save(candidate/'source-tool-audit.json',tool)
    # Recheck receipt closure instead of trusting summary metrics alone.
    expected={}
    for name in ('selection','query'):
        phase=read(candidate/name/'phase-outcome.json')
        for receipt in phase['receipts']['response_receipts']:
            assert receipt['response_id'] not in expected;expected[receipt['response_id']]=receipt['usage']
    actual={}
    for path in candidate.glob('closed-*.jsonl'):
        snap=capture_rollout(path);assert snap.metadata['parse_complete']
        for row in snap.rows:
            if row['type']=='token_usage_record':
                r=row['payload'];assert r['response_id'] not in actual;actual[r['response_id']]=r['usage']
    assert actual==expected and set(actual)==set(result['ledger']['response_ids'])
    assert sum(v['total_tokens'] for v in actual.values())==result['ledger']['study']['tokens']
    value=dict(passed=True,model_calls=0,source_schema_equal=True,request_equal_except_manifest_locator=True,source_objects_verified=len(manifests[0]),
        native_tool_outputs_exact=True,receipt_closure_exact=True,all_cleanup_confirmed=True,
        request_bytes_before=len(encode(read(old/'request.json')).encode()),request_bytes_after=len(encode(request).encode()),
        new_tokens=result['ledger']['study']['tokens'],new_responses=result['ledger']['study']['responses'],score=tool['scores'],
        scope='Single actual C2 qualification, historical baseline; not repeated model equivalence or new B/C comparison.')
    save(args.root/'column-run-audit.json',value);print(value)


if __name__=='__main__':main()
