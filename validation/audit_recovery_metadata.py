"""Measure hypothetical metadata projections, without modifying any tool or history."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def size(value):
    return len(encode(value).encode())


TELEMETRY = {'metrics', 'search_metrics'}
PROOF = {'original_source_id', 'source_record_sha256', 'text_sha256', 'full_text_sha256'}


def project(value, removed):
    # Only declared protocol nodes. Never parse, summarize or inspect source text.
    result = {key: deepcopy(item) for key, item in value.items() if key not in removed}
    if 'matches' in result:
        result['matches'] = [{key: item for key, item in match.items() if key not in removed}
                             for match in result['matches']]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('recovery', nargs='+')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for name in args.recovery:
        path = Path(name)
        raw = path.read_bytes()
        data = json.loads(raw)
        entries = []
        for index, call in enumerate(data['trace']):
            value = call['output']
            telemetry = project(value, TELEMETRY)
            proof = project(value, TELEMETRY | PROOF)
            # Preserve every nonexcluded field, including ranges, states and nulls.
            assert project(telemetry, PROOF) == proof
            assert value == call['output']
            entries.append(dict(index=index, arguments=call['arguments'],
                call_id=call['call_id'], original_bytes=size(value),
                telemetry_hidden_bytes=size(telemetry), proof_hidden_bytes=size(proof),
                source_text_bytes=sum(len(n.get('text','').encode()) for n in [value,*value.get('matches',[])]),
                original_sha256=sha256(encode(value).encode()).hexdigest(),
                telemetry_projection_sha256=sha256(encode(telemetry).encode()).hexdigest(),
                proof_projection_sha256=sha256(encode(proof).encode()).hexdigest()))
        cases.append(dict(path=str(path), sha256=sha256(raw).hexdigest(), entries=entries))
    entries = [e for c in cases for e in c['entries']]
    totals = {key:sum(e[key] for e in entries) for key in
              ('original_bytes','telemetry_hidden_bytes','proof_hidden_bytes','source_text_bytes')}
    result = dict(kind='offline_hypothetical_recovery_metadata_audit', new_model_calls=0,
        calls=len(entries), cases=cases, totals=totals,
        telemetry_fields=sorted(TELEMETRY), proof_fields=sorted(PROOF),
        actual_token_savings=None, task_quality_verified=False,
        tool_behavior_changed=False, projection_is_lossless=False,
        note='Removed fields would no longer be directly answerable. Diagnostic only; no deployed projection.')
    (output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__ == '__main__':
    main()
