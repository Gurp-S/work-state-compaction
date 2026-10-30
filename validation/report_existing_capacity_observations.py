"""Extract existing native capacity telemetry, without querying a live host."""
from hashlib import sha256
from pathlib import Path
import argparse
import json


def read(path, pins):
    raw = path.read_bytes()
    pins[str(path)] = sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    pins = {}
    inventory = read(Path(__file__).parents[1] / 'reviews/existing-continuation-latency-v2/analysis.json', pins)
    phases = []
    for recorded in inventory['phases']:
        root = Path(recorded['root'])
        outcome = read(root / 'phase-outcome.json', pins)
        thread = outcome['thread_id']
        turn = outcome['usage_completion_evidence']['turn_id']
        path = root / 'events.jsonl'
        raw = path.read_bytes()
        pins[str(path)] = sha256(raw).hexdigest()
        observations = []
        excluded = 0
        for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
            event = json.loads(line)
            if event.get('method') != 'thread/tokenUsage/updated':
                continue
            params = event.get('params', {})
            if params.get('threadId') != thread or params.get('turnId') != turn:
                excluded += 1
                continue
            usage = params.get('tokenUsage', {})
            observations.append(dict(line=number, emitted_at_ms=event.get('emittedAtMs'),
                reported_model_context_window=usage.get('modelContextWindow'),
                reported_last_input_tokens=usage.get('last', {}).get('inputTokens'),
                reported_cumulative_input_tokens=usage.get('total', {}).get('inputTokens')))
        phases.append(dict(name=recorded['name'], root=str(root), thread_id=thread, turn_id=turn,
                           completed=outcome['completed'], usage_complete=outcome['usage_complete'],
                           failure=outcome.get('failure'), observations=observations,
                           unrelated_updates_excluded=excluded,
                           billed_input_tokens=outcome['receipts']['all_usage'].get('input_tokens'),
                           next_request_input_tokens=None, next_request_output_reserve_tokens=None,
                           next_request_capacity_verified=False))
    pins[str(Path(__file__))] = sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(scope='Historical event extraction only; no new model calls, host queries, tests, or experiments.',
                  phases=phases, input_sha256=pins,
                  interpretation='Reported window is response-time telemetry for the bound thread/turn, not a preflight guarantee. Last and cumulative usage are distinct; neither is compressed-context size or the next request forecast.')
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/'observations.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    observations = [r for p in phases for r in p['observations']]
    print(json.dumps(dict(phases=len(phases), observations=len(observations),
                         reported_windows=sorted({r['reported_model_context_window'] for r in observations
                                                  if type(r['reported_model_context_window']) is int}),
                         phases_without_observations=[p['name'] for p in phases if not p['observations']],
                         unrelated_updates_excluded=sum(p['unrelated_updates_excluded'] for p in phases)), ensure_ascii=False))


if __name__ == '__main__':
    main()
