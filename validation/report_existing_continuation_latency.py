"""Offline attribution of existing receipts; never opens sessions or runs trials."""
from pathlib import Path
import argparse
import csv
import hashlib
import json

from analyze_turn_latency_20261027 import analyze


RUNS = Path('D:/agent-task-runs')
SUCCESS = [
    RUNS / 'wsc-c1-columns-qualification-20261027-v1',
    RUNS / 'wsc-c1-columns-repeats-20261027-v1/R02',
    RUNS / 'wsc-c1-columns-repeats-20261027-v1/R03',
]
NATIVE = [
    RUNS / 'wsc-late-native-counterpart-20261027-v1/B',
    RUNS / 'wsc-late-remaining-pairs-20261027-v1/R02/B',
    RUNS / 'wsc-late-remaining-pairs-20261027-v1/R03/B',
]
FAILED = RUNS / 'wsc-deferred-catalog-qualification-20261027-v1'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def timeline(root):
    path = root / 'timing.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    headers = [r for r in rows if r['type'] == 'header']
    if len(headers) != 1:
        raise ValueError('timing_header_ambiguous')
    spans = [r for r in rows if r['type'] == 'span']
    if any(r['end_ns'] < r['start_ns'] for r in spans):
        raise ValueError('timing_interval_reversed')
    start, end = headers[0]['monotonic_ns'], max(r['end_ns'] for r in spans)
    points = sorted({start, end} | {r[k] for r in spans for k in ('start_ns', 'end_ns')})
    buckets = dict(stage_execute_and_account=0, selection_outside_stage=0,
                   process_lifecycle=0, other_instrumented_rpc=0, uninstrumented=0)
    for left, right in zip(points, points[1:]):
        if left < start or right > end:
            continue
        labels = [r['label'] for r in spans if r['start_ns'] <= left and right <= r['end_ns']]
        if 'stage.execute_and_account' in labels:
            key = 'stage_execute_and_account'
        elif any(x.startswith('selection.pipeline.') for x in labels):
            key = 'selection_outside_stage'
        elif any(x == 'integration.bootstrap' or x.startswith(('integration.start.', 'integration.close.'))
                 or x in ('integration.bootstrap_close', 'rpc.close') for x in labels):
            key = 'process_lifecycle'
        elif any(x.startswith('rpc.') for x in labels):
            key = 'other_instrumented_rpc'
        else:
            key = 'uninstrumented'
        buckets[key] += right - left
    if sum(buckets.values()) != end - start:
        raise ValueError('timing_partition_incomplete')
    callbacks = []
    for event in rows:
        if event['type'] != 'received_event' or event.get('method') != 'item/tool/call':
            continue
        stamp, component = event['received_monotonic_ns'], event['component']
        stages = [s for s in spans if s['label'] == 'stage.execute_and_account'
                  and s['metadata'].get('component') == component
                  and s['start_ns'] <= stamp <= s['end_ns']]
        record = dict(component=component, thread_id=event['thread_id'], turn_id=event['turn_id'],
                      call_id=event['call_id'], request_id=event['request_id'],
                      received_ns=stamp, reply_local_envelope_seconds=None, local_send_seconds=None)
        if len(stages) != 1:
            record['pairing_error'] = 'stage_ambiguous'
        else:
            stage = stages[0]
            sends = [s for s in spans if s['label'] == 'rpc.send' and s['parent'] == stage['id']
                     and s['metadata'].get('component') == component
                     and s['metadata'].get('response_id') == event['request_id']
                     and stamp <= s['start_ns'] <= s['end_ns'] <= stage['end_ns']]
            if len(sends) != 1:
                record['pairing_error'] = 'reply_ambiguous_or_missing'
            else:
                send = sends[0]
                record.update(reply_local_envelope_seconds=(send['end_ns'] - stamp) / 1e9,
                              local_send_seconds=(send['end_ns'] - send['start_ns']) / 1e9)
        callbacks.append(record)
    result = load(root / 'result.json')
    return dict(root=str(root), recorded_timeline_seconds=(end-start)/1e9,
                disjoint_seconds={k: v/1e9 for k, v in buckets.items()}, callbacks=callbacks,
                outer_seconds=result.get('seconds') if root != SUCCESS[0] else None,
                outer_seconds_note='R01 outer coordinator failed; recorded timeline is a lower bound.'
                if root == SUCCESS[0] else 'Separate outer monotonic interval; not the same endpoints as this timeline.',
                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    jobs = []
    for index, root in enumerate(SUCCESS, 1):
        jobs.extend((f'C/R{index:02d}/{stage}', root / 'R01' / stage)
                    for stage in ('C1-selection', 'C2-selection', 'wsc-probe'))
    for index, root in enumerate(NATIVE, 1):
        jobs.extend((f'B/R{index:02d}/{stage}', root / stage)
                    for stage in ('B1-compression', 'B2-compression', 'query'))
    jobs.append(('failed/deferred_catalog/selection', FAILED / 'candidate/selection'))
    phases = []
    pins = {}
    for name, root in jobs:
        row = dict(name=name, root=str(root))
        try:
            row.update(analyze(root))
        except (ValueError, KeyError, TypeError, OSError) as error:
            row['analysis_error'] = type(error).__name__ + ': ' + str(error)
        phases.append(row)
        for filename in ('phase-outcome.json', 'events.jsonl'):
            path = root / filename
            pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    timelines = []
    for root in SUCCESS + NATIVE + [FAILED]:
        try:
            timelines.append(timeline(root))
        except (ValueError, KeyError, TypeError, OSError) as error:
            timelines.append(dict(root=str(root), analysis_error=type(error).__name__ + ': ' + str(error)))
        for filename in ('timing.jsonl', 'result.json'):
            path = root / filename
            pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    output = dict(scope='Existing artifacts only; no new model calls, tests, timing trials, or sessions.',
                  phases=phases, timelines=timelines, input_sha256=pins,
                  pure_model_compute_seconds=None, provider_queue_seconds=None,
                  network_seconds=None, local_disk_io_seconds=None,
                  callback_note='Received callback through completed local send: includes logging, scheduling, handler and serialization; not pure disk I/O. Separate from server tool intervals; do not add them.',
                  timeline_note='Disjoint local interval partition. Uninstrumented includes core work and coordinator checks; not pure WSC overhead. Separate clocks are never subtracted as absolute timestamps.')
    output['successful_per_chain_means'] = {}
    for scheme in ('C', 'B'):
        selected = [r for r in phases if r['name'].startswith(scheme + '/')]
        if len(selected) == 9 and not any('analysis_error' in r for r in selected):
            output['successful_per_chain_means'][scheme] = {
                key: sum(r[key] for r in selected) / 3
                for key in ('phase_seconds', 'server_turn_seconds', 'dynamic_tool_union_seconds',
                            'server_non_tool_seconds', 'phase_outside_server_turn_seconds')}
    for path in (Path(__file__), Path(__file__).with_name('analyze_turn_latency_20261027.py'),
                 Path(__file__).parents[1] / 'experiments/native_latency.py'):
        output['input_sha256'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    columns = ['name', 'phase_seconds', 'server_turn_seconds', 'dynamic_tool_count',
               'dynamic_tool_union_seconds', 'server_non_tool_seconds',
               'phase_outside_server_turn_seconds', 'failure', 'analysis_error']
    with (args.out / 'phases.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(phases)
    print(json.dumps(dict(phases=len(phases), phase_errors=[r for r in phases if 'analysis_error' in r],
                          timelines=len(timelines), timeline_errors=[r for r in timelines if 'analysis_error' in r]), ensure_ascii=False))


if __name__ == '__main__':
    main()
