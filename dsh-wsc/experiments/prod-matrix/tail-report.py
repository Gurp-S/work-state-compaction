"""Tail report: where the cost of a long session actually goes.

Per run: main/extraction cost, compactions, spill reads and dedupe pointers per
turn, pointers emitted after the first compaction of a turn (the ones R1
removes), and environmental references kept inside checkpoints (R2/R3).

Usage: python tail-report.py --scenario long-40 --arms v2,v2f
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs'
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
COST = (1.0, 0.02, 4.0)
ENV = re.compile(r'dsh-spill-|AppData[\\/]Local[\\/]Temp|out[\\/]round-\d+\.(?:jsonl|txt)')
POINTER = re.compile(r'\[denoise: ([^\]]*)\]')
PIN = re.compile(r'## Unresolved error\n- ([^\n]*)')


def load_session(session: str) -> list[dict]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        return [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]


def tool_text(message: dict) -> str:
    content = message.get('content') or []
    return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict))


def per_turn(events: list[dict]) -> dict:
    turns = {}
    turn = None
    comps = 0
    calls = {}
    for event in events:
        kind = event.get('type')
        data = event.get('data') or {}
        if kind == 'tool/call':
            turn = data.get('turn', turn)
            slot = turns.setdefault(turn, {'comps': 0, 'spills': 0, 'pointers': 0, 'latePointers': 0,
                                           'steps': 0, 'reads': 0, 'edits': 0, 'dedupe': 0, 'lateDedupe': 0})
            slot['steps'] = max(slot['steps'], int(data.get('step') or 0))
            args = str(data.get('arguments') or '')
            if 'dsh-spill' in args:
                slot['spills'] += 1
            calls[data.get('callId')] = data.get('name')
        elif kind == 'tool/result':
            turn = data.get('turn', turn)
            slot = turns.setdefault(turn, {'comps': 0, 'spills': 0, 'pointers': 0, 'latePointers': 0,
                                           'steps': 0, 'reads': 0, 'edits': 0, 'dedupe': 0, 'lateDedupe': 0})
            text = tool_text(data.get('message') or {})
            found = POINTER.search(text)
            if found is not None:
                slot['pointers'] += 1
                dedupe = bool(re.search(r'dedupe_(?:reads|identical)', found.group(1)))
                if dedupe:
                    slot['dedupe'] += 1
                if slot['comps'] >= 1:
                    slot['latePointers'] += 1
                    if dedupe:
                        slot['lateDedupe'] += 1
        elif kind == 'compaction/start':
            comps += 1
            where = data.get('turn', turn)
            if where is not None:
                slot = turns.setdefault(where, {'comps': 0, 'spills': 0, 'pointers': 0, 'latePointers': 0,
                                                'steps': 0, 'reads': 0, 'edits': 0, 'dedupe': 0, 'lateDedupe': 0})
                slot['comps'] += 1
    return turns


def checkpoints(events: list[dict]) -> dict:
    env_refs = pin_env = pins = total = 0
    for event in events:
        if event.get('type') != 'compaction/summary':
            continue
        total += 1
        text = ''.join(block.get('text', '') for block in (event.get('data') or {}).get('summary') or []
                       if block.get('type') == 'text')
        env_refs += len(ENV.findall(text))
        for line in PIN.findall(text):
            pins += 1
            if ENV.search(line) or line.startswith('<path>'):
                pin_env += 1
    return {'checkpoints': total, 'envRefs': env_refs, 'pins': pins, 'pinEnv': pin_env}


def round_cost(out: Path) -> dict:
    rows = {}
    for path in sorted(out.glob('round-*.jsonl')):
        number = int(path.stem.split('-')[1])
        usage = [0, 0, 0]
        steps = 0
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get('type') == 'status' and event.get('phase') == 'step_end':
                values = event.get('usage') or {}
                used = int(values.get('inputTokens') or 0)
                cache = int(values.get('cacheReadTokens') or 0)
                usage[0] += max(0, used - cache)
                usage[1] += cache
                usage[2] += int(values.get('outputTokens') or 0)
                steps += 1
        cost = (usage[0] * COST[0] + usage[1] * COST[1] + usage[2] * COST[2]) / 1_000_000
        rows[number] = {'cost': cost, 'steps': steps}
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='long-40')
    parser.add_argument('--arms', default='v2,v2f')
    parser.add_argument('--reps', default='')
    parser.add_argument('--brief', action='store_true')
    args = parser.parse_args()
    reps = [int(part) for part in args.reps.split(',') if part.strip()] if args.reps else []

    for arm in [part.strip() for part in args.arms.split(',') if part.strip()]:
        for directory in sorted((RUNS / args.scenario / arm).glob('rep*')):
            if reps and int(directory.name[3:]) not in reps:
                continue
            done = directory / 'done'
            if not done.exists():
                continue
            session = done.read_text(encoding='utf-8').strip()
            events = load_session(session)
            turns = per_turn(events)
            cp = checkpoints(events)
            costs = round_cost(directory / 'out')
            metrics = {}
            if (directory / 'metrics.json').exists():
                metrics = json.loads((directory / 'metrics.json').read_text(encoding='utf-8'))
            total = sum(row['cost'] for row in costs.values())
            main_turns = sorted(costs.items(), key=lambda item: -item[1]['cost'])[:3]
            spills = sum(slot['spills'] for slot in turns.values())
            late = sum(slot['latePointers'] for slot in turns.values())
            dedupe = sum(slot['dedupe'] for slot in turns.values())
            lateDedupe = sum(slot['lateDedupe'] for slot in turns.values())
            if args.brief:
                print(f"{args.scenario} {arm} {directory.name}: main={total:.3f} "
                      f"ext={metrics.get('extractionCostCny', 0):.3f} "
                      f"total={metrics.get('totalCostCny', 0):.3f} "
                      f"steps={metrics.get('steps', 0)} comps={sum(slot['comps'] for slot in turns.values())} "
                      f"spills={spills} dedupe={dedupe} lateDedupe={lateDedupe} latePtr={late} cpEnv={cp['envRefs']} pinEnv={cp['pinEnv']} "
                      f"cpMax={max(metrics.get('checkpointChars') or [0])} "
                      f"probe={metrics.get('probePassed', '?')}/{metrics.get('probeTotal', '?')} "
                      f"tests={metrics.get('testsPassed', '?')}")
                continue
            print(f"\n{args.scenario}/{arm}/{directory.name}: session={session[:18]}.. "
                  f"steps={metrics.get('steps', '?')} comps={sum(t['comps'] for t in turns.values())} "
                  f"main={total:.3f} ext={metrics.get('extractionCostCny', 0):.3f} "
                  f"total={metrics.get('totalCostCny', 0):.3f} "
                  f"probe={metrics.get('probePassed', '?')}/{metrics.get('probeTotal', '?')} "
                  f"tests={metrics.get('testsPassed', '?')} cpMax={max(metrics.get('checkpointChars') or [0])}")
            print(f"  checkpoints: envRefs={cp['envRefs']} pins={cp['pins']} pinEnv={cp['pinEnv']}")
            for turn, slot in sorted(turns.items()):
                if slot['spills'] or slot['pointers'] or slot['comps']:
                    print(f"  t{turn}: steps={slot['steps']} comps={slot['comps']} spills={slot['spills']} "
                          f"pointers={slot['pointers']} dedupe={slot['dedupe']} "
                          f"latePointers={slot['latePointers']} lateDedupe={slot['lateDedupe']}")
            print('  top rounds: ' + ', '.join(
                f"r{number}={row['cost']:.3f}/{row['steps']}st" for number, row in main_turns))


if __name__ == '__main__':
    main()
