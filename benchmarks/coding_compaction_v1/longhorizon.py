"""Six-round drift run: does a compacted state keep constraints and current
verification as rounds accumulate, and does an old verification stay retracted?

The fixture extends each authored case with four generated rounds. Each round
adds a numbered constraint, an edit and a check (or a check claim after the
edit). Scoring is per round: constraint retention in the current claims, the
latest verification present, older verifications absent, and bytes.

DSH native carries its previous checkpoint into the next compaction; the thin
layer carries its ledger/state. WSC is not run here: its four-call round is
superseded by the thin layer and would triple the run without adding a new arm.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import cases as case_module  # noqa: E402
from coding_compaction_v1 import live  # noqa: E402


BUDGET = 32768


def first_path(case: dict) -> str:
    """The file the case actually edits; generated rounds follow the same file."""
    for delta in (case['items'], case['round2']['items']):
        for item in delta:
            if item.get('type') == 'function_call' and item.get('name') == 'edit':
                try:
                    path = json.loads(item.get('arguments') or '{}').get('file_path')
                except ValueError:
                    path = None
                if path:
                    return path
    return 'src/wsc/resource_io.py'


def generated_round(path: str, number: int) -> list:
    items = []
    if number % 2 == 1:
        items += [case_module._call(f'e{number}', 'edit', {'file_path': path,
                                                          'new_string': f'round {number} change'}),
                  case_module._output(f'e{number}', 'ok')]
        items += case_module._burst(f'bt{number}', 10 + number)
    else:
        items += [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
                   'text': f'V{number} checked after the edit to {path}'}]}]
        items += case_module._burst(f'bt{number}', 10 + number)
    items += [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
               'text': f'Requirement: round {number} constraint marker C{number} must hold'}]}]
    return items


def constraint_needles(case: dict) -> list:
    """Constraints by round: round-1 oracle, extra round-2 constraints, then C3..C6."""
    first = [fact.get('needle') or fact['text'] for fact in case['oracle']['ledger']
             if fact['kind'] == 'constraint']
    second = [fact.get('needle') or fact['text'] for fact in case['round2']['oracle']['ledger']
              if fact['kind'] == 'constraint']
    return first + second + [f'round {number} constraint marker C{number}'
                             for number in (3, 4, 5, 6)]


def expected_rounds(case: dict) -> list:
    """How many constraint needles are live after each round."""
    first = [fact for fact in case['oracle']['ledger'] if fact['kind'] == 'constraint']
    second = [fact for fact in case['round2']['oracle']['ledger'] if fact['kind'] == 'constraint']
    counts = [len(first), len(first) + len(second)]
    counts += [counts[-1] + 1 for _ in (3, 4, 5, 6)]
    return counts


def run_native_chain(model, case, rounds, budget):
    presented, out = None, []
    for number, delta in enumerate(rounds, 1):
        result = live.run_native(model, delta, presented, budget,
                                 label=f'{case["case"]}:lh-native-r{number}')
        presented = result['presented']
        out.append(result)
    return out


def run_thin_chain(model, case, rounds, budget):
    entries, next_id, items_all, events_all = [], 1, [], []
    control, presented = [], []
    out = []
    for number, delta in enumerate(rounds, 1):
        base = len(items_all)
        events = live.CodexCheckpointAdapter().import_items(
            delta, thread_id=case['case'], start_ordinal=base,
            observed_at=live.observed_at(base, len(delta)))
        items_all += delta
        events_all += events
        control += [event.text for event in events
                    if event.kind == 'message' and event.role == 'user' and (event.text or '').strip()]
        rows = [{'ref': entry['ref'], 'kind': entry['kind'], 'text': entry['text']}
                for entry in entries if entry['status'] == 'active']
        raw = live.thin_call(model, delta, rows, out[-1]['state'] if out else {}, number,
                             label=f'{case["case"]}:lh-thin-r{number}')
        next_id = live.thin_apply(entries, raw, delta, base=base, next_id=next_id)
        live.thin_expire(entries, events_all, base=base if number > 1 else 0)
        repaired = live.repair_identifiers(entries, events_all)
        receipts = live.receipts_from_events(events_all)
        state = live.thin_state(raw, receipts, entries)
        index = live.index_from_events(events_all)
        archive = live.archive_from_events(events_all)
        work = {'control': control,
                'rounds': {number: {'entries': [dict(entry) for entry in entries],
                                    'state': state, 'archive': archive, 'index': index,
                                    'dropped': live.archived_without_slot(events_all, index)}},
                'receipts': {number: receipts}}
        text = live.thin_render(work, number, budget)
        out.append({'presented': text, 'bytes': len(text.encode()), 'state': state,
                    'entries': [dict(entry) for entry in entries],
                    'receipts': receipts, 'index': index, 'repaired': repaired})
    return out


def check_round(number: int, presented: str, constraints: list,
                verification: str | None) -> dict:
    current = live.claims_text(presented)
    kept = sum(needle in current for needle in constraints)
    stale = any(f'V{earlier} checked' in current
                for earlier in range(4, number) if earlier % 2 == 0)
    return {'round': number,
            'constraints_kept': kept, 'constraints_total': len(constraints),
            'constraint_rate': round(kept / len(constraints), 4) if constraints else None,
            'verification_present': bool(verification and verification in current),
            'stale_earlier_verification': stale,
            'bytes': len(presented.encode())}


def measure(model, case, out):
    path = first_path(case)
    rounds = [case['items'], case['round2']['items']] + \
             [generated_round(path, number) for number in (3, 4, 5, 6)]
    native = run_native_chain(model, case, rounds, BUDGET)
    thin = run_thin_chain(model, case, rounds, BUDGET)
    constraints = constraint_needles(case)
    counts = expected_rounds(case)
    report = {'case': case['case'], 'path': path, 'rounds': len(rounds),
              'native': [], 'thin': []}
    for position, number in enumerate(range(1, len(rounds) + 1)):
        verification = f'V{number} checked' if number >= 4 and number % 2 == 0 else None
        live_constraints = constraints[:counts[position]]
        for arm, chain in (('native', native), ('thin', thin)):
            report[arm].append(check_round(number, chain[position]['presented'],
                                           live_constraints, verification))
    report['drift'] = {
        'native_constraint_6': report['native'][-1]['constraint_rate'],
        'thin_constraint_6': report['thin'][-1]['constraint_rate'],
        'native_stale_5': report['native'][4]['stale_earlier_verification'],
        'thin_stale_5': report['thin'][4]['stale_earlier_verification'],
        'native_bytes_growth': report['native'][-1]['bytes'] - report['native'][0]['bytes'],
        'thin_bytes_growth': report['thin'][-1]['bytes'] - report['thin'][0]['bytes'],
        'thin_repaired': sum(len(row.get('repaired') or []) for row in thin),
    }
    directory = out / case['case']
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'drift.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding='utf-8')
    (directory / 'presented-native-r6.txt').write_text(native[-1]['presented'], encoding='utf-8')
    (directory / 'presented-thin-r6.txt').write_text(thin[-1]['presented'], encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'benchmarks' / 'coding_compaction_v1' / 'runs')
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args(argv)
    out = args.out / ('lh-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    model = live.Model(live.load_key())
    selected = [factory() for factory in case_module.CASES]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [(case, pool.submit(measure, model, case, out)) for case in selected]
        for case, future in futures:
            report = future.result()
            results.append(report)
            print(f"\n{case['case']}  rounds={report['rounds']}")
            for arm in ('native', 'thin'):
                rows = report[arm]
                print(f"  {arm:<7} constraints " + ' '.join(f"{row['constraint_rate']:.2f}"
                                                       for row in rows)
                      + '  bytes ' + ' '.join(str(row['bytes']) for row in rows)
                      + f"  stale_5 {report['drift'][arm + '_stale_5']}")
            print(f"  drift {report['drift']}")
    (out / 'summary.json').write_text(json.dumps({'model': live.MODEL, 'results': results},
                                                 ensure_ascii=False, indent=2), encoding='utf-8')
    print('\noutput', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
