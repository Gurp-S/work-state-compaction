"""Final ranking table on a fair cost basis.

Cost = agent steps + the compaction model calls + nosig extraction calls.
Native records its compaction call usage on the `compaction/summary` event;
the earlier matrix rows only summed agent steps, so those rows understate it.
WSC arms record extraction usage in the journal; three old w80 rows predate
that field and are estimated from the known w80 samples (marked *).
"""
from __future__ import annotations

import glob
import io
import json
import os
import statistics
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs'
SESSIONS = Path(os.environ.get('DSH_HOME', str(Path.home() / '.dsh'))) / 'sessions'
COST = (1.0, 0.02, 4.0)


def summary_call_cost(session: str) -> tuple[float, int]:
    matches = glob.glob(str(SESSIONS / '*' / session / 'session.v4.jsonl.zstd'))
    if not matches:
        return 0.0, 0
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(open(matches[0], 'rb').read())) as reader:
        events = [json.loads(line) for line in reader.read().decode('utf-8').splitlines() if line.strip()]
    total = 0.0
    calls = 0
    for event in events:
        if event.get('type') != 'compaction/summary':
            continue
        usage = (event.get('data') or {}).get('usage') or {}
        if not usage:
            continue
        calls += 1
        uncached = max(0, int(usage.get('inputTokens') or 0) - int(usage.get('cacheReadTokens') or 0))
        total += (uncached * COST[0] + int(usage.get('cacheReadTokens') or 0) * COST[1]
                  + int(usage.get('outputTokens') or 0) * COST[2]) / 1_000_000
    return total, calls


def w80_estimate_per_compaction() -> float:
    rates = []
    for directory in sorted((RUNS / 'long-40' / 'w80').glob('rep*')):
        metrics = directory / 'metrics.json'
        if not metrics.exists():
            continue
        row = json.loads(metrics.read_text(encoding='utf-8'))
        if row.get('extractionKnown') and row['compactions'] > 0:
            rates.append(row['extractionCostCny'] / row['compactions'])
    return statistics.median(rates) if rates else 0.02


def collect(scenario: str) -> list[dict]:
    rate = w80_estimate_per_compaction() if scenario == 'long-40' else 0.0
    rows = []
    for arm_dir in sorted((RUNS / scenario).glob('*')):
        for rep_dir in sorted(arm_dir.glob('rep*')):
            metrics_path = rep_dir / 'metrics.json'
            if not (rep_dir / 'done').exists() or not metrics_path.exists():
                continue
            metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
            session = (rep_dir / 'done').read_text().strip()
            extra, calls = summary_call_cost(session)
            extraction = metrics['extractionCostCny']
            estimated = ''
            if (arm_dir.name == 'w80' and not metrics.get('extractionKnown')
                    and metrics['compactions'] > 0 and scenario == 'long-40'):
                extraction = round(rate * metrics['compactions'], 4)
                estimated = '*'
            deep_path = rep_dir / 'deep.json'
            deep = json.loads(deep_path.read_text(encoding='utf-8')) if deep_path.exists() else {}
            rows.append({
                'scenario': scenario, 'arm': arm_dir.name, 'rep': metrics['repeat'],
                'total': round(metrics['costCny'] + extraction + extra, 4),
                'main': metrics['costCny'], 'ext': extraction, 'summary': round(extra, 4),
                'estimated': estimated, 'compactions': metrics['compactions'],
                'wall': deep.get('wall'), 'cpFinal': deep.get('cpFinal'), 'cpMax': deep.get('cpMax'),
                'compress': deep.get('compress'), 'verbatim': deep.get('verbatim'),
                'coverage': deep.get('coverage'), 'citations': deep.get('citations'),
                'envrefs': deep.get('envrefs'), 'rework': deep.get('rework'),
                'offtask': deep.get('offtask'), 'edits': deep.get('edits'),
                'forbidden': deep.get('forbidden'), 'reread': deep.get('reread'), 'reads': deep.get('reads'),
                'probe': deep.get('probe'), 'oracle': deep.get('oracle'),
                'tests': f"{metrics.get('testsPassed')}/{metrics.get('testsPassed', 0) + metrics.get('testsFailed', 0)}",
            })
    return rows


def median(rows: list[dict], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return statistics.median(values) if values else None


def main() -> None:
    orders = {
        'long-40': ['v3r', 'v2f', 'w80', 'native', 'v4q', 'v3b', 'v3i', 'ledger'],
        'constraint-25': ['v3r', 'v2f', 'w80', 'native'],
    }
    for scenario, arms in orders.items():
        rows = collect(scenario)
        print(f'== {scenario}')
        print('arm | n | cost_med | range | comps | wall_med | cp_last | cp_max | probe | oracle | tests | verbatim | citations | coverage | env | rework | offtask | forbidden | reread')
        for arm in arms:
            sel = [row for row in rows if row['arm'] == arm]
            if not sel:
                continue
            totals = [row['total'] for row in sel]
            probes = [row['probe'] for row in sel if row.get('probe')]
            passed = sum(int(p.split('/')[0]) for p in probes)
            total_probe = sum(int(p.split('/')[1]) for p in probes)
            oracles = [row['oracle'] for row in sel if row.get('oracle') and row['oracle'] != '-']
            oracle_min = min((int(o.split('/')[0]) for o in oracles), default=None)
            est = '*' if any(row['estimated'] for row in sel) else ''
            def joined(key):
                values = [row[key] for row in sel if row.get(key) not in (None, '-')]
                return ','.join(str(v) for v in values)
            print(' | '.join(str(x) for x in (
                arm, len(sel), f"{statistics.median(totals):.3f}{est}",
                f"{min(totals):.3f}-{max(totals):.3f}",
                f"{median(sel, 'compactions'):.0f}",
                f"{median(sel, 'wall'):.0f}" if median(sel, 'wall') else '-',
                f"{median(sel, 'cpFinal'):.0f}" if median(sel, 'cpFinal') else '-',
                f"{max(row['cpMax'] for row in sel if row.get('cpMax'))}" if any(row.get('cpMax') for row in sel) else '-',
                f"{passed}/{total_probe or '-'}",
                f"{oracle_min}/54" if oracle_min is not None else '-',
                joined('tests'), sel[0].get('verbatim', '-'),
                joined('citations'), joined('coverage'), joined('envrefs'),
                joined('rework'), f"{sum(row.get('offtask') or 0 for row in sel)}",
                joined('forbidden'), joined('reread'))))
        print()


if __name__ == '__main__':
    main()
