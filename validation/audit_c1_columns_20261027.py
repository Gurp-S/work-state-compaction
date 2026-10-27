"""Prove actual C1 wire equivalence with explicitly enumerated fork identities."""
from pathlib import Path
from copy import deepcopy
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_event_columns import restore as restore_events
from native_metadata_columns import restore as restore_metadata
from native_evidence import read,save,file_hash
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from wsc.contracts import encode


def main():
    p=argparse.ArgumentParser()
    for name in ('root','source'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();old=args.source/'R01/C1-generation';new=args.root/'R01/C1-generation'
    left=read(old/'request.json');right=read(new/'request.json');original_right=deepcopy(right)
    proof,submitted=verify_transcript(capture_rollout(args.root/'R01/C1-selection/rollout.jsonl'),read(args.root/'R01/C1-selection/phase-outcome.json'))
    assert encode(submitted)==encode(original_right) and proof==read(new/'request-binding.json')
    right['material']=restore_metadata(restore_events(right['material'],read(new/'event-columns-binding.json')),read(new/'metadata-column-binding.json'))
    for value in (left,right):
        for key in ('path','sha256'):value['material']['cold_source_manifest'].pop(key)
        value['material']['frontier_boundary'].pop('source_digest')
    assert encode(left)==encode(right)
    assert encode(read(old/'schema.json'))==encode(read(new/'schema.json'))
    a=read(old/'resource-manifest.json')['cold_sources'];b=read(new/'resource-manifest.json')['cold_sources'];assert list(a)==list(b)
    for key in a:
        # Fresh native fork changes source identities. No content normalization.
        assert file_hash(a[key]['path'])==a[key]['sha256'] and file_hash(b[key]['path'])==b[key]['sha256']
        x=read(a[key]['path']);y=read(b[key]['path']);x.pop('id');y.pop('id');assert encode(x)==encode(y)
    admission=read(Path(read(args.root/'registration.json')['source'])/'R01/C1-generation/request.json')
    phases={}
    for name in ('C1-selection','C2-selection','wsc-probe'):
        value=read(args.root/'R01'/name/'phase-outcome.json');phases[name]=dict(seconds=value['seconds'],usage=value['receipts']['all_usage'],responses=value['receipts']['response_count'])
    result=dict(passed=True,model_calls=0,source_objects_verified=len(a),C1_schema_exact=True,C1_spans_fields_order_exact=True,
        normalized_fields=['material.cold_source_manifest.path','material.cold_source_manifest.sha256','material.frontier_boundary.source_digest','cold-object.id (fresh fork identity only)'],
        original_source_database_sha256=file_hash(args.source/'R01/state.db'),request_bytes_before=len(encode(read(old/'request.json')).encode()),request_bytes_after=len(encode(original_right).encode()),
        phase_metrics=phases,full_chain_tokens=sum(p['usage']['total_tokens'] for p in phases.values()),coordinator_recovery=read(args.root/'result.json').get('recovered_from_durable_receipts',False),
        scope='Original public content/schema exact, new model choices allowed. One full C chain, historical comparison, not three prospective B/C pairs.')
    destination=args.root/'C1-equivalence-audit.json'
    if destination.exists():assert read(destination)==result
    else:save(destination,result)
    print(result)


if __name__=='__main__':main()
