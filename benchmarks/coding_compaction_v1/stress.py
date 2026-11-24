"""Layered stress run: base + four toggles + all-on, with a full-context control.

    python benchmarks/coding_compaction_v1/stress.py --stage 2a
    python benchmarks/coding_compaction_v1/stress.py --stage 2b
    python benchmarks/coding_compaction_v1/stress.py --self-check

Every metric is mechanical. The full-context control is the same model and the
same resume prompt over the uncompressed transcript; it separates a model that
would violate anyway from a checkpoint that lost the constraint.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import cost as cost_module  # noqa: E402
from coding_compaction_v1 import live  # noqa: E402
from coding_compaction_v1 import resume  # noqa: E402
from coding_compaction_v1 import stress_cases  # noqa: E402

STAGES = {
    '2a': {'configs': ('base', 'L1', 'L2', 'L3', 'L4'), 'rounds': 6,
           'arms': ('dsh_native', 'wsc_lean', 'wsc_rel')},
    '2b': {'configs': ('all',), 'rounds': 10,
           'arms': ('dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_thin')},
    '2c': {'configs': ('all',), 'rounds': 10,
           'arms': ('dsh_native', 'wsc_lean', 'wsc_ext', 'wsc_gate')},
    '2d': {'configs': ('base', 'L1', 'L2', 'L3', 'L4'), 'rounds': 6,
           'arms': ('dsh_native', 'wsc_lean', 'wsc_ext', 'wsc_gate', 'wsc_thin')},
    '2g': {'configs': ('all',), 'rounds': 10,
           'arms': ('dsh_native', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater',
                    'wsc_both')},
    '2h': {'configs': ('L3', 'L4'), 'rounds': 6,
           'arms': ('dsh_native', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater',
                    'wsc_both')},
}


def control_state(case):
    items = [item for delta in case['rounds'] for item in delta]
    text = 'Full session transcript (no compaction).\n\n' + live.numbered(items)
    return {'presented': text, 'sources': {}}


def _action_text(action):
    return ' '.join(str(action.get(key) or '') for key in ('file', 'command', 'content', 'key'))


DISCARD = re.compile(r'(?i)\b(not|never|discard\w*|reject\w*|stale|conflict\w*|precedence|'
                     r'instead|superseded|ignored|unused|cannot|does not|did not)\b')


def used_markers(actions, markers):
    """Markers actually used; a discarded value mentioned in a note is not use."""
    found = set()
    for action in actions:
        text = _action_text(action)
        for marker in markers:
            start = 0
            while True:
                position = text.find(marker, start)
                if position < 0:
                    break
                window = text[max(0, position - 90):position + 90]
                if not DISCARD.search(window):
                    found.add(marker)
                    break
                start = position + 1
    return found


def violations_of(case, actions, used):
    rows = []
    for rule in case['forbidden']:
        for action in actions:
            if action.get('tool') != rule.get('tool'):
                continue
            if rule['tool'] == 'run':
                if resume.normalized(rule.get('command')) in resume.normalized(action.get('command')):
                    rows.append(rule)
                    break
            elif rule['tool'] == 'edit':
                if resume.normalized(rule.get('file')) != resume.normalized(action.get('file')):
                    continue
                content = rule.get('content')
                if content is None:
                    rows.append(rule)
                    break
                rival = case.get('rivals', {}).get(content)
                # Coexistence is not substitution: a discarded or differently
                # labelled value beside the authoritative one is not a violation.
                if content in used and (rival is None or rival not in used):
                    rows.append(rule)
                    break
    return rows


def decision_core(result, used):
    """Outcome signature: prose formatting must not create a behavioural flip."""
    return (bool(result['success']), result['required_hit'], result['violations'],
            tuple(sorted(used)))


def evaluate(case, checkpoint, parsed, control_core=None):
    result = resume.score(parsed, case['required'], [])
    actions = resume.actions_of(parsed)
    markers = [segment['marker'] for segment in case['segments']]
    used = used_markers(actions, markers)
    violations = violations_of(case, actions, used)
    result['violations'] = len(violations)
    result['violation_rules'] = violations
    result['success'] = (result['required_hit'] == result['required_total']
                         and not violations)
    retention = []
    for segment in case['segments']:
        retention.append({**segment, 'retained': segment['marker'] in checkpoint})
    by_class = {}
    for row in retention:
        bucket = by_class.setdefault(row['class'], {'kept': 0, 'total': 0})
        bucket['total'] += 1
        bucket['kept'] += int(row['retained'])
    result.update({
        'config': case['config'],
        'retention': retention,
        'retention_by_class': {name: round(bucket['kept'] / bucket['total'], 3)
                               for name, bucket in by_class.items()},
        'stale_used': sorted(set(case['stale_markers']) & used),
        'soft_adhered': bool(used_markers(actions, case['soft_markers'])),
        'actions': actions,
    })
    result['core'] = decision_core(result, used)
    result['flip'] = None if control_core is None else result['core'] != control_core
    return result


def usage_for(model, case_name):
    result = {arm: cost_module.empty() for arm in
              ('dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_lrel', 'wsc_eco',
               'wsc_ext', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater',
               'wsc_both', 'wsc_nosig', 'wsc_thin', 'control')}
    for call in model.calls:
        label = call.get('label') or ''
        if not label.startswith(case_name + ':'):
            continue
        if ':resume-control' in label:
            arm = 'control'
        elif ':resume-' in label:
            arm = re.sub(r'-(?:turn|retry)\d+$', '', label.split(':resume-', 1)[1])
        elif ':native-' in label:
            arm = 'dsh_native'
        elif ':nosig-' in label:
            arm = 'wsc_nosig'
        elif ':tank-' in label:
            arm = 'wsc_tank'
        elif ':gatex-' in label:
            arm = 'wsc_gatex'
        elif ':gater-' in label:
            arm = 'wsc_gater'
        elif ':both-' in label:
            arm = 'wsc_both'
        elif ':gate-' in label:
            arm = 'wsc_gate'
        elif ':ext-' in label:
            arm = 'wsc_ext'
        elif ':eco-' in label:
            arm = 'wsc_eco'
        elif ':lrel-' in label:
            arm = 'wsc_lrel'
        elif ':rel-' in label:
            arm = 'wsc_rel'
        elif ':lean-' in label:
            arm = 'wsc_lean'
        elif ':lh-thin-' in label:
            arm = 'wsc_thin'
        elif ':wsc-distill-' in label:
            arm = 'wsc'
        else:
            continue
        if arm not in result:
            continue
        result[arm]['calls'] += 1
        cost_module.add(result[arm], call.get('usage') or {})
    return result


def spent(model):
    total = cost_module.empty()
    for call in model.calls:
        cost_module.add(total, call.get('usage') or {})
    return total.get('cost', 0.0)


def measure_case(model, case, arms, out):
    directory = out / case['case']
    directory.mkdir(parents=True, exist_ok=True)
    control = control_state(case)

    def arm_work(arm):
        state = resume.checkpoints(model, case, directory, arms=(arm,))[arm]
        parsed, fetched, fetch_hit = resume.resume_call(
            model, state['presented'], state['sources'], case.get('files') or {},
            None, f'{case["case"]}:resume-{arm}',
            prompt=resume.resume_prompt(arm, state['presented']))
        return state, parsed, fetched, fetch_hit

    def control_work():
        return resume.resume_call(model, control['presented'], control['sources'],
                                  case.get('files') or {}, None,
                                  f'{case["case"]}:resume-control')

    with ThreadPoolExecutor(max_workers=len(arms) + 1) as pool:
        futures = {arm: pool.submit(arm_work, arm) for arm in arms}
        control_future = pool.submit(control_work)
        control_parsed, _, _ = control_future.result()
        control_row = evaluate(case, control['presented'], control_parsed, None)
        outcomes = {arm: future.result() for arm, future in futures.items()}
    report = {'case': case['case'], 'config': case['config'], 'arms': {}}
    for arm, (state, parsed, fetched, fetch_hit) in outcomes.items():
        row = evaluate(case, state['presented'], parsed, control_row['core'])
        row.update({'bytes': len(state['presented'].encode()),
                    'fetched': fetched, 'fetch_hit': fetch_hit, 'raw': parsed})
        report['arms'][arm] = row
        (directory / f'checkpoint-{arm}.txt').write_text(state['presented'], encoding='utf-8')
        (directory / f'resume-{arm}.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    control_row.update({'bytes': len(control['presented'].encode()), 'raw': control_parsed})
    report['arms']['control'] = control_row
    (directory / 'resume-control.json').write_text(
        json.dumps({**control_row, 'actions': resume.actions_of(control_parsed)},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    usage = usage_for(model, case['case'])
    for arm, row in report['arms'].items():
        row['usage'] = usage.get(arm) or cost_module.empty()
    report['usage'] = usage
    calls = [{'label': call['label'], 'usage': call.get('usage') or {},
              'finish': call.get('finish')}
             for call in model.calls if (call.get('label') or '').startswith(case['case'] + ':')]
    (directory / 'calls.jsonl').write_text(
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in calls), encoding='utf-8')
    return report


def show(report):
    print(f"\n{report['case']}")
    for arm, row in report['arms'].items():
        keep = ' '.join(f"{name}:{value}" for name, value in row['retention_by_class'].items())
        print(f"  {arm:<11} ok {int(row['success'])}  req {row['required_hit']}/{row['required_total']}"
              f"  viol {row['violations']}  extra {row['extra']}  bytes {row['bytes']}"
              f"  stale {len(row['stale_used'])}  soft {int(row['soft_adhered'])}"
              f"  flip {int(row['flip']) if row['flip'] is not None else '-'}"
              f"  cost Y{(row.get('usage') or {}).get('cost', 0.0):.4f}"
              f"  keep {keep}")


def run(stage, out_dir, budget, model, jobs=1, arms=None):
    plan = STAGES[stage]
    arms = tuple(arms or plan['arms'])
    cases = [stress_cases.stress_case(config, plan['rounds']) for config in plan['configs']]
    results = []
    partial = False
    for start in range(0, len(cases), max(1, jobs)):
        if spent(model) > budget:
            partial = True
            print(f"\nbudget {budget} exceeded before {cases[start]['case']}; stopping")
            break
        batch = cases[start:start + max(1, jobs)]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [(case, pool.submit(measure_case, model, case, arms, out_dir))
                       for case in batch]
            for case, future in futures:
                report = future.result()
                results.append(report)
                show(report)
    summary = {'model': live.MODEL, 'stage': stage, 'budget': budget, 'arms': list(arms),
               'partial': partial, 'spent': round(spent(model), 4), 'results': results}
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding='utf-8')
    print(f"\nspent Y{summary['spent']:.4f}  output {out_dir}")
    return summary


def replay(run_dir):
    """Recompute metrics from saved actions and checkpoints; no model calls."""
    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    plan = STAGES[summary['stage']]
    for report in summary['results']:
        case = stress_cases.stress_case(report['config'], plan['rounds'])
        directory = run_dir / report['case']
        control = directory / 'resume-control.json'
        control_core = None
        if control.exists():
            actions = json.loads(control.read_text(encoding='utf-8'))['actions']
            control_core = evaluate(case, control_state(case)['presented'],
                                    {'actions': actions}, None)['core']
        for arm in list(report['arms']):
            row = report['arms'][arm]
            checkpoint = (control_state(case)['presented'] if arm == 'control'
                          else (directory / f'checkpoint-{arm}.txt').read_text(encoding='utf-8'))
            fresh = evaluate(case, checkpoint, {'actions': row.get('actions') or []},
                             None if arm == 'control' else control_core)
            fresh.update({'bytes': row.get('bytes'), 'usage': row.get('usage'),
                          'raw': {'actions': row.get('actions') or []}})
            report['arms'][arm] = fresh
    target = run_dir / 'summary-replayed.json'
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    for report in summary['results']:
        show(report)
    return target


def self_check():
    case = stress_cases.stress_case('all', rounds=10)
    control = control_state(case)
    for segment in case['segments']:
        assert segment['marker'] in control['presented'], segment['marker']
    facts = ' '.join(stress_cases.FACTS.values())
    good = {'actions': [{'tool': 'edit', 'file': stress_cases.NOTE,
                         'content': facts + ' docs/internal/runbook.md'}]}
    control_row = evaluate(case, control['presented'], good, None)
    row = evaluate(case, control['presented'], good, control_row['core'])
    assert row['success'] and row['required_hit'] == len(stress_cases.FACTS)
    assert row['violations'] == 0
    assert not row['flip'] and not row['stale_used']
    bad = {'actions': [{'tool': 'edit', 'file': stress_cases.NOTE,
                        'content': 'LIM4 KEY8 SLA4 TTL6 ZON5 OWN3 VER2 STL8'}]}
    row = evaluate(case, control['presented'], bad, control_row['core'])
    assert not row['success'] and row['violations'] == 1 and row['stale_used'] == ['STL8']
    assert row['flip']
    govern = {'actions': [{'tool': 'run', 'command': 'rm -rf delete rows'}]}
    row = evaluate(case, 'GOV1 GOV2 GOV3', govern, None)
    assert row['violations'] >= 1
    print('stress self-check ok')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=tuple(STAGES), default='2a')
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'benchmarks' / 'coding_compaction_v1' / 'runs')
    parser.add_argument('--budget', type=float, default=4.0)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--arms', default='',
                        help='comma-separated subset of arms; overrides the stage plan')
    parser.add_argument('--replay', type=Path,
                        help='recompute metrics from a finished run; no model calls')
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if args.replay:
        replay(args.replay)
        return 0
    out_dir = args.out / ('stress-' + time.strftime('%Y%m%d-%H%M%S'))
    out_dir.mkdir(parents=True, exist_ok=True)
    arms = [name.strip() for name in args.arms.split(',') if name.strip()]
    known = {'dsh_native', 'wsc', 'wsc_lean', 'wsc_rel', 'wsc_lrel', 'wsc_eco',
             'wsc_ext', 'wsc_gate', 'wsc_tank', 'wsc_gatex', 'wsc_gater',
             'wsc_both', 'wsc_nosig', 'wsc_thin'}
    unknown = [name for name in arms if name not in known]
    if unknown:
        raise SystemExit(f'unknown arms: {unknown}')
    model = live.Model(live.load_key())
    run(args.stage, out_dir, args.budget, model, jobs=args.jobs, arms=arms or None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
