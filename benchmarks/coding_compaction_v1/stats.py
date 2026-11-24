"""Aggregate repeated live/resume runs into per-arm means and standard deviations.

One run is a sample: model reasoning, 429 retries and judge sampling all move the
numbers. This script reads several run directories of the same kind and reports
the mean +/- sd of each arm's cost and score, plus the mean judge scores when
judge files are present.

    python benchmarks/coding_compaction_v1/stats.py <run-dir> [<run-dir> ...]
    python benchmarks/coding_compaction_v1/stats.py --json <run-dir> ...

Live and resume directories are detected from their ``summary.json`` shape and
reported separately.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'benchmarks')]

from coding_compaction_v1 import cost as cost_module  # noqa: E402

ARMS = ('dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_lrel', 'wsc_eco',
        'wsc_ext', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater', 'wsc_both',
        'wsc_nosig', 'wsc_nosig_v1', 'wsc_nored', 'wsc_next', 'wsc_thin')


def _cost(usage):
    """Exact yuan cost; older summaries kept only prompt/completion totals."""
    if not usage:
        return None
    if 'cost' in usage:
        return usage['cost']
    details = usage.get('prompt_tokens_details') or {}
    return cost_module.cost_from_tokens(usage.get('prompt_tokens', 0),
                                        usage.get('completion_tokens', 0),
                                        details.get('cached_tokens', 0))


def _summary(run):
    path = run / 'summary.json'
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def _kind(summary):
    results = (summary or {}).get('results') or []
    if not results:
        return None
    return 'live' if 'gate' in results[0] else 'resume'


def _mean_sd(values):
    values = [value for value in values if value is not None]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


def _live_sample(result):
    rows = {}
    for arm, row in result['arms'].items():
        if arm.endswith('_matched'):
            continue
        usage = row.get('usage') or {}
        rows[arm] = {
            'cases': 1,
            'calls': usage.get('calls', 0),
            'prompt': usage.get('prompt_tokens', 0),
            'completion': usage.get('completion_tokens', 0),
            'cost': _cost(usage),
            'bytes': int(row['bytes']['2']),
            'probe': row['scores']['2'].get('probe'),
            'recall': row['scores']['2'].get('key_recall'),
        }
    return rows


def _resume_sample(result):
    rows = {}
    for arm, row in result['arms'].items():
        usage = row.get('usage') or {}
        comp = usage.get('compression') or {}
        resume = usage.get('resume') or {}
        measured = bool(comp or resume)
        comp_cost, resume_cost = _cost(comp), _cost(resume)
        rows[arm] = {
            'cases': 1,
            'success': int(bool(row.get('success'))),
            'successes': int(bool(row.get('success'))),
            'extra': row.get('extra', 0),
            'bytes': row.get('bytes', 0),
            'prompt': comp.get('prompt_tokens') if measured else None,
            'completion': comp.get('completion_tokens') if measured else None,
            'resume_tokens': (resume.get('prompt_tokens', 0) + resume.get('completion_tokens', 0))
            if measured else None,
            'cost': round((comp_cost or 0) + (resume_cost or 0), 6) if measured else None,
        }
    return rows


MEAN_KEYS = {'probe', 'recall', 'success'}


def _aggregate(runs, kind):
    per_run = []
    for run, summary in runs:
        fields = {}
        for result in summary['results']:
            case_sample = _live_sample(result) if kind == 'live' else _resume_sample(result)
            for arm, row in case_sample.items():
                target = fields.setdefault(arm, {key: [] for key in row})
                for key, value in row.items():
                    if value is not None:
                        target[key].append(value)
        totals = {}
        for arm, values in fields.items():
            totals[arm] = {}
            for key, items in values.items():
                if not items:
                    totals[arm][key] = None
                elif key in MEAN_KEYS:
                    totals[arm][key] = statistics.mean(items)
                else:
                    totals[arm][key] = sum(items)
            if kind == 'live':
                cases = totals[arm].get('cases') or 0
                totals[arm]['cost_per_case'] = (totals[arm]['cost'] / cases
                                                if totals[arm].get('cost') is not None and cases else None)
            else:
                successes = totals[arm].get('successes') or 0
                totals[arm]['cost_per_success'] = (totals[arm]['cost'] / successes
                                                   if totals[arm].get('cost') is not None and successes
                                                   else None)
        per_run.append(totals)
    arms = [arm for arm in ARMS if any(arm in totals for totals in per_run)]
    table = {}
    for arm in arms:
        keys = next(totals[arm] for totals in per_run if arm in totals)
        table[arm] = {}
        for key in keys:
            mean, sd = _mean_sd([totals.get(arm, {}).get(key) for totals in per_run])
            table[arm][key] = {'mean': mean, 'sd': sd}
    return table


def _judges(runs):
    """Mean judge score and wins per arm across the judge files of resume runs."""
    scores, wins, files = {}, {}, []
    for run, summary in runs:
        for path in sorted(run.glob('judge-*.json')):
            name = path.name
            if 'before-rubric' in name or 'nometa' in name:
                continue
            payload = json.loads(path.read_text(encoding='utf-8'))
            if 'seed' not in payload:
                # Older rubric versions are not comparable; only current samples.
                continue
            files.append(name)
            for scenario in payload.get('scenarios') or []:
                for arm, row in (scenario.get('scores') or {}).items():
                    scores.setdefault(arm, []).append(row.get('overall'))
                top = (scenario.get('ranking') or [None])[0]
                if top:
                    wins[top] = wins.get(top, 0) + 1
    result = {}
    for arm in sorted(set(scores) | set(wins)):
        values = scores.get(arm) or []
        result[arm] = {'overall': round(statistics.mean(values), 3) if values else None,
                       'wins': wins.get(arm, 0), 'samples': len(values)}
    return {'files': files, 'arms': result}


def _fmt(row, percent=False, money=False):
    mean, sd = row['mean'], row['sd']
    if mean is None:
        return '-'
    if money:
        return f'Y{mean:.4f} +/-{sd:.4f}'
    if percent:
        return f'{mean * 100:.0f}% +/-{(sd * 100):.0f}%'
    if mean >= 1000:
        return f'{mean / 1000:.1f}k +/-{sd / 1000:.1f}k'
    return f'{mean:.2f} +/-{sd:.2f}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    groups = {'live': [], 'resume': []}
    for run in args.runs:
        summary = _summary(run)
        kind = _kind(summary)
        if kind is None:
            print(f'skip {run}: no readable summary.json')
            continue
        groups[kind].append((run, summary))
    report = {}
    for kind in ('live', 'resume'):
        if not groups[kind]:
            continue
        report[kind] = {'runs': [str(run) for run, _ in groups[kind]],
                        'arms': _aggregate(groups[kind], kind)}
    if groups['resume']:
        report['judge'] = _judges(groups['resume'])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for kind in ('live', 'resume'):
        if kind not in report:
            continue
        print(f"\n{kind}  runs={len(report[kind]['runs'])}")
        if kind == 'live':
            print(f"{'arm':<11}{'calls':<9}{'prompt':<16}{'completion':<16}{'bytes':<17}"
                  f"{'probe':<14}{'recall':<16}{'cost/case'}")
            for arm, row in report[kind]['arms'].items():
                print(f"{arm:<11}{_fmt(row['calls']):<9}{_fmt(row['prompt']):<16}"
                      f"{_fmt(row['completion']):<16}{_fmt(row['bytes']):<17}"
                      f"{_fmt(row['probe']):<14}{_fmt(row['recall']):<16}"
                      f"{_fmt(row['cost_per_case'], money=True)}")
        else:
            print(f"{'arm':<11}{'success':<12}{'extra':<9}{'bytes':<17}"
                  f"{'prompt':<16}{'completion':<16}{'resume':<16}{'cost/success'}")
            for arm, row in report[kind]['arms'].items():
                print(f"{arm:<11}{_fmt(row['success'], True):<12}{_fmt(row['extra']):<9}"
                      f"{_fmt(row['bytes']):<17}{_fmt(row['prompt']):<16}"
                      f"{_fmt(row['completion']):<16}{_fmt(row['resume_tokens']):<16}"
                      f"{_fmt(row['cost_per_success'], money=True)}")
    if 'judge' in report:
        print(f"\njudge  files={len(report['judge']['files'])}")
        for arm, row in report['judge']['arms'].items():
            print(f"  {arm:<11} overall {row['overall']}  wins {row['wins']}  samples {row['samples']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
