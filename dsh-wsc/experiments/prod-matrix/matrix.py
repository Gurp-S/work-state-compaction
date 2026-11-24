"""Production-style matrix: native vs nosig baseline vs nosig fix, many scenarios.

Each run is one headless DSH session over a scripted round list in a private copy
of a seed repository. Runs are isolated by workspace and session id, execute in
parallel worker processes, retry transient gateway failures, and record one row
per run in summary.csv.

Usage:
  python matrix.py plan --repeats feature-25=2,long-40=2,refactor-18=3,bugfix-16=3 --arms native,wsc,fix
  python matrix.py run  --jobs 4 --repeats ... --arms ...
  python matrix.py analyze
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent
SCEN = HERE / 'scenarios'
RUNS = HERE / 'runs'
DEFAULT_ARMS = {'native': 'native-eval', 'wsc': 'wsc-eval', 'fix': 'wsc-fix',
                'cap': 'wsc-cap', 'ws': 'wsc-ws', 'sf': 'wsc-sf', 'w80': 'wsc-w80', 'old': 'wsc-old', 'off': 'wsc-off', 'cmd': 'wsc-cmd', 'ledger': 'wsc-ledger',
                'ws2': 'wsc-ws2', 'cmdws': 'wsc-cmdws', 'cards': 'wsc-cards', 'lcards': 'wsc-lcards',
                'dclean': 'wsc-dclean', 'v2': 'wsc-v2', 'v2f': 'wsc-v2', 'base': 'wsc-v3r', 'v3i': 'wsc-v3i', 'v3x': 'wsc-v3x', 'v3r': 'wsc-v3r', 'v3b': 'wsc-v3b',
                'v4q': 'wsc-v4q'}
CLI = os.environ.get('DSH_CLI', 'dsh')
NODE_EXE = os.environ.get('DSH_NODE_EXE', '')
KEY_FILE = os.environ.get('NEW_API_KEY_FILE', '')
DSH_HOME = os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))
SESSIONS = Path(DSH_HOME) / 'sessions'
TRANSIENT = re.compile(r'429|503|overloaded|SERVER|ECONNRESET|ETIMEDOUT|timed out|already owned|rate.?limit|rpm limit|tpm/rpm', re.I)
COST = (1.0, 0.02, 4.0)  # CNY per M: uncached input, cached input, output


def load_rounds(scenario: str) -> list[str]:
    return json.loads((SCEN / scenario / 'rounds.json').read_text(encoding='utf-8'))


def write_bat(path: Path, profile: str, task: str, session: str) -> None:
    task = task.replace('"', '""')
    sid = f'--session-id {session} ' if session else ''
    lines = [
        '@echo off',
        f'set DSH_HOME={DSH_HOME}',
        f'set DSH_DESKTOP_NODE_EXECUTABLE={NODE_EXE}',
        *(['set WSC_DEBUG=1'] if os.environ.get('MATRIX_WSC_DEBUG') == '1' else []),
        *([f'set /p NEW_API_API_KEY=<{KEY_FILE}'] if KEY_FILE else []),
        f'call "{CLI}" --profile {profile} headless --json --permission-mode workspace-write '
        f'--approval-policy never {sid}"{task}"',
    ]
    path.write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8')


def round_ok(path: Path) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if '\"type\":\"final\"' in line or '"type": "final"' in line:
            return True
    return False


def error_text(path: Path) -> str:
    if not path.exists():
        return ''
    found = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get('type') == 'error':
            found.append(str(event.get('message', '')))
        if event.get('type') == 'final' and event.get('reason', {}).get('kind') == 'error':
            found.append(str(event.get('reason', {}).get('error', {}).get('message', '')))
    return ' | '.join(found)


def run_dir(scenario: str, arm: str, repeat: int) -> Path:
    return RUNS / scenario / arm / f'rep{repeat}'


def run_one(scenario: str, arm: str, repeat: int, progress) -> None:
    profile = DEFAULT_ARMS[arm]
    directory = run_dir(scenario, arm, repeat)
    workspace = directory / 'ws'
    out = directory / 'out'
    if (directory / 'done').exists():
        progress(f'{scenario}/{arm}/rep{repeat}: already done')
        return
    out.mkdir(parents=True, exist_ok=True)
    if not workspace.exists():
        shutil.copytree(SCEN / scenario / 'seed', workspace)
    rounds = load_rounds(scenario)
    session = ''
    for number, task in enumerate(rounds, 1):
        target = out / f'round-{number:02d}.jsonl'
        if round_ok(target) and (out / f'round-{number:02d}.ok').exists():
            continue
        attempts = 0
        wait = 30
        while True:
            attempts += 1
            bat = out / f'round-{number:02d}.bat'
            write_bat(bat, profile, task, session)
            started = time.time()
            with open(target, 'w', encoding='utf-8', errors='replace') as stdout, \
                    open(out / f'round-{number:02d}.stderr.txt', 'w', encoding='utf-8', errors='replace') as stderr:
                try:
                    subprocess.run(['cmd', '/c', str(bat)], cwd=workspace, stdout=stdout, stderr=stderr,
                                   timeout=1500, check=False)
                except subprocess.TimeoutExpired:
                    pass
            elapsed = int(time.time() - started)
            if not session:
                for line in target.read_text(encoding='utf-8', errors='replace').splitlines():
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get('type') == 'session' and event.get('sessionId'):
                        session = event['sessionId']
                        break
            reason = error_text(target)
            ok = round_ok(target) and reason == ''
            progress(f'{scenario}/{arm}/rep{repeat}: round {number:02d} '
                     f'{"ok" if ok else "FAIL"} {elapsed}s attempt {attempts}'
                     + (f' :: {reason[:160]}' if reason else ''))
            if ok:
                (out / f'round-{number:02d}.ok').write_text('ok', encoding='utf-8')
                break
            if attempts >= 4 or (reason and not TRANSIENT.search(reason)):
                progress(f'{scenario}/{arm}/rep{repeat}: stop at round {number} :: {reason[:200]}')
                (directory / 'failed').write_text(reason or 'no final event', encoding='utf-8')
                return
            time.sleep(wait)
            wait *= 2
    (directory / 'done').write_text(session, encoding='utf-8')
    progress(f'{scenario}/{arm}/rep{repeat}: finished session={session}')


def load_session(session: str) -> list[dict]:
    if not session:
        return []
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return []
    with open(matches[0], 'rb') as handle:
        data = handle.read()
    with zstandard.ZstdDecompressor().stream_reader(__import__('io').BytesIO(data)) as reader:
        text = reader.read().decode('utf-8')
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def probe_score(scenario: str, out: Path) -> tuple[int, int]:
    spec = json.loads((SCEN / scenario / 'probe.json').read_text(encoding='utf-8'))
    groups = spec.get('facts', [])
    number = len(load_rounds(scenario))
    path = out / f'round-{number:02d}.jsonl'
    if not path.exists():
        return 0, len(groups)
    texts = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get('type') == 'final' and isinstance(event.get('text'), str):
            texts.append(event['text'])
    haystack = '\n'.join(texts).lower()

    def fact_ok(group):
        if isinstance(group, dict):
            must = group.get('must') or []
            forbid = group.get('forbid') or []
            return (all(str(word).lower() in haystack for word in must)
                    and not any(str(word).lower() in haystack for word in forbid))
        return all(str(word).lower() in haystack for word in group)

    passed = sum(1 for group in groups if fact_ok(group))
    return passed, len(groups)


def run_tests(workspace: Path) -> tuple[bool, int, int]:
    try:
        result = subprocess.run(['node', '--test'], cwd=workspace, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=300, shell=False)
    except Exception:
        return False, 0, 0
    text = (result.stdout or '') + (result.stderr or '')
    passed = re.search(r'\u2139 pass (\d+)', text)
    failed = re.search(r'\u2139 fail (\d+)', text)
    if not passed:
        return result.returncode == 0, 0, 0
    count = int(passed.group(1))
    failures = int(failed.group(1)) if failed else 0
    return result.returncode == 0 and failures == 0, count, failures


def round_metrics(out: Path) -> dict:
    steps = tool_calls = 0
    uncached = cached = output = 0
    calls = {}
    for path in sorted(out.glob('round-*.jsonl')):
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get('type') == 'status' and event.get('phase') == 'step_end':
                usage = event.get('usage') or {}
                tokens_in = int(usage.get('inputTokens') or 0)
                cache = int(usage.get('cacheReadTokens') or 0)
                uncached += max(0, tokens_in - cache)
                cached += cache
                output += int(usage.get('outputTokens') or 0)
                steps += 1
            elif event.get('type') == 'tool_call':
                tool_calls += 1
                calls[event.get('tool', '?')] = calls.get(event.get('tool', '?'), 0) + 1
    cost = (uncached * COST[0] + cached * COST[1] + output * COST[2]) / 1_000_000
    return {'steps': steps, 'toolCalls': tool_calls, 'tools': calls,
            'uncachedPrompt': uncached, 'cachedPrompt': cached, 'outputTokens': output,
            'costCny': round(cost, 4)}


def compaction_metrics(session: str) -> dict:
    events = load_session(session)
    summaries = [event for event in events if event.get('type') == 'compaction/summary']
    sizes, shadowed = [], []
    for event in summaries:
        data = event.get('data') or {}
        chars = sum(len(block.get('text', '')) for block in (data.get('summary') or [])
                    if block.get('type') == 'text')
        sizes.append(chars)
        shadowed.append(data.get('shadowedTokenCount') or 0)
    return {'compactions': len(summaries), 'checkpointChars': sizes, 'shadowedTokens': shadowed}


def extraction_metrics(session: str) -> dict:
    """Sum the nosig extraction calls the session usage does not include."""
    path = Path(DSH_HOME) / 'wsc' / 'nosig' / f'{session}.jsonl'
    if not path.exists():
        return {'extractionCalls': 0, 'extractionInput': 0, 'extractionOutput': 0,
                'extractionCache': 0, 'extractionCostCny': 0.0, 'extractionKnown': False}
    calls = input_tokens = output_tokens = cache = 0
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get('op') != 'usage':
            continue
        usage = row.get('usage') or {}
        calls += int(usage.get('calls') or 0)
        input_tokens += int(usage.get('inputTokens') or 0)
        output_tokens += int(usage.get('outputTokens') or 0)
        cache += int(usage.get('cacheReadTokens') or 0)
    cost = (input_tokens * COST[0] + cache * COST[1] + output_tokens * COST[2]) / 1_000_000
    return {'extractionCalls': calls, 'extractionInput': input_tokens,
            'extractionOutput': output_tokens, 'extractionCache': cache,
            'extractionCostCny': round(cost, 4), 'extractionKnown': calls > 0}


def analyze_run(scenario: str, arm: str, repeat: int) -> dict | None:
    directory = run_dir(scenario, arm, repeat)
    if not (directory / 'done').exists():
        return None
    out = directory / 'out'
    session = (directory / 'done').read_text(encoding='utf-8').strip()
    metrics = {'scenario': scenario, 'arm': arm, 'repeat': repeat, 'session': session}
    metrics.update(round_metrics(out))
    metrics.update(compaction_metrics(session))
    metrics.update(extraction_metrics(session))
    metrics['totalCostCny'] = round(metrics['costCny'] + metrics['extractionCostCny'], 4)
    ok, passed, failed = run_tests(directory / 'ws')
    probe_passed, probe_total = probe_score(scenario, out)
    metrics.update({'testsOk': ok, 'testsPassed': passed, 'testsFailed': failed,
                    'probePassed': probe_passed, 'probeTotal': probe_total})
    (directory / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding='utf-8')
    return metrics


def cmd_run(args) -> None:
    repeats = parse_repeats(args.repeats)
    arms = [arm.strip() for arm in args.arms.split(',') if arm.strip()]
    jobs = []
    for scenario, count in repeats.items():
        for arm in arms:
            for repeat in range(args.rep_start, args.rep_start + count):
                jobs.append((scenario, arm, repeat))
    lock = threading.Lock()

    def progress(message: str) -> None:
        with lock:
            print(message, flush=True)

    queue = list(jobs)
    results = []
    result_lock = threading.Lock()

    def worker(index: int) -> None:
        while True:
            with lock:
                if not queue:
                    return
                scenario, arm, repeat = queue.pop(0)
            run_one(scenario, arm, repeat, progress)
            metrics = analyze_run(scenario, arm, repeat)
            if metrics is not None:
                with result_lock:
                    results.append(metrics)

    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(min(args.jobs, len(jobs)))]
    started = time.time()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    write_summary(results)
    print(f'matrix finished in {int(time.time() - started)}s; rows={len(results)}')


def cmd_plan(args) -> None:
    repeats = parse_repeats(args.repeats)
    arms = [arm.strip() for arm in args.arms.split(',') if arm.strip()]
    runs = sum(repeats.values()) * len(arms)
    print(f'runs={runs} arms={arms} repeats={repeats}')
    print('estimate: 10-22 min per run, 0.25-0.60 CNY per run; '
          f'total ~{runs * 0.3:.1f}-{runs * 0.6:.1f} CNY, '
          f'wall ~{runs * 12 / max(1, args.jobs):.1f} min at jobs={args.jobs}')


def parse_repeats(text: str) -> dict[str, int]:
    out = {}
    for item in text.split(','):
        if not item.strip():
            continue
        name, count = item.split('=')
        out[name.strip()] = int(count)
    return out


def write_summary(results: list[dict]) -> None:
    fields = ['scenario', 'arm', 'repeat', 'session', 'compactions', 'steps', 'toolCalls',
              'uncachedPrompt', 'cachedPrompt', 'outputTokens', 'costCny',
              'extractionCalls', 'extractionInput', 'extractionOutput', 'extractionCache',
              'extractionCostCny', 'totalCostCny', 'extractionKnown',
              'testsOk', 'testsPassed', 'testsFailed', 'probePassed', 'probeTotal',
              'checkpointChars', 'shadowedTokens', 'tools']
    with open(HERE / 'summary.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in sorted(results, key=lambda item: (item['scenario'], item['arm'], item['repeat'])):
            out = {key: row.get(key) for key in fields}
            out['checkpointChars'] = ';'.join(str(value) for value in row.get('checkpointChars') or [])
            out['shadowedTokens'] = ';'.join(str(value) for value in row.get('shadowedTokens') or [])
            out['tools'] = json.dumps(row.get('tools') or {}, ensure_ascii=False)
            writer.writerow(out)


def cmd_analyze(args) -> None:
    results = []
    for scenario in (p.name for p in SCEN.iterdir() if (p / 'rounds.json').exists()):
        for arm_dir in (RUNS / scenario).glob('*') if (RUNS / scenario).exists() else []:
            for rep_dir in arm_dir.glob('rep*'):
                repeat = int(rep_dir.name.replace('rep', ''))
                metrics = analyze_run(scenario, arm_dir.name, repeat)
                if metrics is not None:
                    results.append(metrics)
    write_summary(results)
    for row in results:
        print(f"{row['scenario']:12} {row['arm']:7} rep{row['repeat']} "
              f"main={row['costCny']:.3f} ext={row['extractionCostCny']:.3f} "
              f"total={row['totalCostCny']:.3f} comp={row['compactions']} steps={row['steps']} "
              f"tests={row['testsPassed']}/{row['testsPassed'] + row['testsFailed']} "
              f"probe={row['probePassed']}/{row['probeTotal']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['plan', 'run', 'analyze'])
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--repeats', default='feature-25=2,long-40=2,refactor-18=3,bugfix-16=3')
    parser.add_argument('--arms', default='native,wsc,fix')
    parser.add_argument('--rep-start', type=int, default=1, help='first repeat number (append new samples)')
    args = parser.parse_args()
    if args.command == 'plan':
        cmd_plan(args)
    elif args.command == 'run':
        cmd_run(args)
    else:
        cmd_analyze(args)


if __name__ == '__main__':
    main()
