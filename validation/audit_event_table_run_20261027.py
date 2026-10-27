"""Bind the real table candidate to its unchanged source and baseline request."""
from pathlib import Path
from copy import deepcopy
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_evidence import read,save,file_hash
from native_event_table import restore
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from wsc.contracts import encode


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','root'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();candidate=args.root/'candidate';generation=candidate/'generation'
    original=args.source/'R01/C2-generation';old=read(original/'request.json');new=read(generation/'request.json')
    binding=read(generation/'event-table-binding.json');decoded=deepcopy(new)
    decoded['material']=restore(decoded['material'],binding);assert binding['applied']
    for request in (old,decoded):
        for key in ('path','sha256'):request['material']['cold_source_manifest'].pop(key)
    assert encode(old)==encode(decoded)
    assert encode(read(original/'schema.json'))==encode(read(generation/'schema.json'))
    a=read(original/'resource-manifest.json')['cold_sources'];b=read(generation/'resource-manifest.json')['cold_sources']
    assert list(a)==list(b)
    for alias in a:
        left={k:v for k,v in a[alias].items() if k!='path'};right={k:v for k,v in b[alias].items() if k!='path'}
        assert encode(left)==encode(right)
        assert file_hash(a[alias]['path'])==file_hash(b[alias]['path'])==a[alias]['sha256']
    phase=read(candidate/'selection/phase-outcome.json');proof,submitted=verify_transcript(capture_rollout(candidate/'selection/rollout.jsonl'),phase)
    assert encode(submitted)==encode(new) and proof==read(generation/'request-binding.json')
    result=read(args.root/'result.json');assert result['status']=='completed' and not result['ledger']['study']['uncertain']
    audit=read(candidate/'source-tool-audit.json');assert audit['passed']
    result=dict(passed=True,model_calls=0,source_schema_unchanged=True,decoded_request_equal_except_host_manifest_locator=True,
        source_objects_verified=len(a),request_bytes_before=len(encode(read(original/'request.json')).encode()),
        request_bytes_after=len(encode(new).encode()),new_score=audit['scores'],new_tokens=result['ledger']['study']['tokens'],
        source_database_sha256=file_hash(args.source/'R01/state.db'),
        scope='Exact representation and single-run behavior audit; does not prove universal semantic equivalence, timing or native superiority.')
    save(args.root/'table-run-audit.json',result);print(result)


if __name__=='__main__':main()
