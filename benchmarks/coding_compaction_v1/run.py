"""Run the coding-agent compaction fixtures across reference arms and rounds.

Every execution must compress. Per arm and round the runner refuses a material
that exceeds the fixed byte budget, and the product arm must also satisfy
ratio <= 0.85 with verified evidence; otherwise the case is invalid.

Discrimination is a checked property of the set: on each case, the probe score
spread across the three reference arms must be at least MIN_SPREAD. A case that
cannot separate truncation, salience extraction and the state ledger is not an
eval item.

Two rounds are scored. Baselines re-summarize their own previous output plus
the new tail; the product arm continues the same ledger, where entries cite
durable seq pointers and mechanically expire when a cited file changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from wsc import WSC, Store, Selection, Understanding, Limits  # noqa: E402
from wsc.adapters.codex import CodexCheckpointAdapter  # noqa: E402
from compaction_acceptance import fidelity_profile, reversibility  # noqa: E402
from coding_compaction_v1 import arms, cases as case_module  # noqa: E402

MAX_RATIO = 0.85
MIN_SPREAD = 0.15
DEFAULT_BUDGET_FRACTION = 0.5
RATIO_TOLERANCE = 0.05
WSC_ARMS = ('wsc_evidence_only', 'wsc_sticky', 'wsc')


def flatten(value) -> str:
    return arms.flatten(value)


def _observed(index: int) -> str:
    return f'2026-11-17T{index // 60:02d}:{index % 60:02d}:00Z'


def _find(items: list, needle: str) -> int:
    for index, item in enumerate(items):
        if needle in flatten(item):
            return index
    raise ValueError('case_needle_missing: ' + needle)


def _round_oracle(case: dict, round_number: int) -> dict:
    return case['oracle'] if round_number == 1 else case['round2']['oracle']


def _round_probes(case: dict, round_number: int) -> list:
    return case['probes'] if round_number == 1 else case['round2']['probes']


def fact_catalog(case: dict) -> dict:
    catalog = {}
    for oracle in (case['oracle'], case['round2']['oracle']):
        for fact in oracle['evidence'] + oracle['ledger']:
            catalog[fact['id']] = fact['text']
    return catalog


def probe_report(probes: list, catalog: dict, presented: str) -> dict:
    """Expected facts must be present; excluded (stale) facts must be absent."""
    hits = total = 0
    failures, stale = [], []
    for probe in probes:
        for fact_id in probe['expects']:
            total += 1
            if catalog[fact_id] in presented:
                hits += 1
            else:
                failures.append({'probe': probe['question'], 'missing': fact_id})
        for fact_id in probe.get('excludes', []):
            total += 1
            if catalog[fact_id] not in presented:
                hits += 1
            else:
                stale.append(fact_id)
    return {'score': round(hits / total, 4) if total else None, 'hits': hits,
            'total': total, 'failures': failures, 'stale_present': stale}


def oracle_report(case: dict, round_number: int, presented: str) -> dict:
    facts = _round_oracle(case, round_number)
    rows = facts['evidence'] + facts['ledger']
    retained = {row['id']: row['text'] in presented for row in rows}
    constraints = [row for row in facts['ledger'] if row['kind'] == 'constraint']
    return {
        'key_recall': round(sum(retained.values()) / len(retained), 4) if retained else None,
        'constraint_retention': round(sum(retained[f['id']] for f in constraints) / len(constraints), 4)
        if constraints else None,
        'missing': [key for key, value in retained.items() if not value],
    }


def catalog_report(catalog: dict, presented: str, stale: set | None = None) -> dict:
    """Long-horizon retention over every fact the case ever stated.

    A superseded fact is satisfied by its absence: keeping it would present a
    stale claim as current, which the probes already penalize.
    """
    stale = stale or set()
    retained = {key: ((text not in presented) if key in stale else (text in presented))
                for key, text in catalog.items()}
    return {'key_recall': round(sum(retained.values()) / len(retained), 4),
            'missing': [key for key, value in retained.items() if not value],
            'stale_kept': [key for key in stale if catalog[key] in presented]}


def verify_evidence(package: dict) -> dict:
    verified = {}
    for source_id, locator in package.get('evidence', {}).items():
        path = Path(locator['file_path'])
        try:
            verified[source_id] = (path.is_file()
                                   and hashlib.sha256(path.read_bytes()).hexdigest() == locator['sha256'])
        except OSError:
            verified[source_id] = False
    return verified


def wsc_rounds(case: dict, root: Path, budget: int, *, distill: bool = True,
               expiry: bool = True) -> dict:
    """One product-pipeline configuration across both rounds."""
    adapter = CodexCheckpointAdapter()
    core = WSC(Store(root / 'case.db', session_id=case['case'], workspace=str(root)),
               access=lambda *args: True)
    items1 = case['items']
    ids1 = core.ingest(adapter.import_items(items1, thread_id=case['case'],
                                            observed_at=[_observed(i) for i in range(len(items1))]))
    core.presented('round-1', tuple(ids1), receiver='offline-model')
    evidence1 = sorted({_find(items1, fact['needle']) for fact in case['oracle']['evidence']})

    def understandings(entries, ids, items, prefix):
        if not distill:
            return ()
        return tuple(
            Understanding(text=entry['text'], kind=entry['kind'], id=f"{case['case']}-{prefix}{index}",
                          sources=(ids[_find(items, entry['text'])],),
                          **({'invalid_when': entry['invalid_when']}
                             if expiry and 'invalid_when' in entry else {}))
            for index, entry in enumerate(entries))

    view1 = core.prepare(
        core.capture(),
        Selection(source_ids=tuple(ids1[index] for index in evidence1),
                  new_understandings=understandings(case['distill'], ids1, items1, 'd')),
        producer='oracle-selector', limits=Limits(max_view_bytes=budget))
    operation1 = core.stage(view1, directory=root / 'round-1', adapter=adapter)
    package1 = core.package(operation1)
    # The measured package was never submitted; releasing the slot keeps the
    # next round a fresh, independent compression rather than a replay.
    core.discard(operation1)
    presented1 = flatten(package1['items'])

    items2 = case['round2']['items']
    ids2 = core.ingest(adapter.import_items(items2, thread_id=case['case'],
                                            start_ordinal=len(items1),
                                            observed_at=[_observed(len(items1) + i) for i in range(len(items2))]))
    core.presented('round-2', tuple(ids2), receiver='offline-model')
    items_all, ids_all = items1 + items2, ids1 + ids2
    evidence2 = sorted({_find(items_all, fact['needle']) for fact in case['round2']['oracle']['evidence']}
                       | {_find(items_all, fact['needle']) for fact in case['oracle']['evidence']})
    view2 = core.prepare(
        core.capture(),
        Selection(source_ids=tuple(ids_all[index] for index in evidence2),
                  new_understandings=understandings(case['round2']['distill'], ids_all,
                                                    items_all, 'r2d')),
        producer='oracle-selector', limits=Limits(max_view_bytes=budget))
    package2 = core.package(core.stage(view2, directory=root / 'round-2', adapter=adapter))
    return {'presented': {1: presented1, 2: flatten(package2['items'])},
            'package': package2,
            'verified': verify_evidence(package2)}


def baseline_rounds(case: dict, budget: int) -> dict:
    """Truncation and salience extraction over identical chunks and budget."""
    chunks1 = arms.chunks_of(case['items'])
    chunks2 = arms.chunks_of(case['round2']['items'])
    out = {}
    for name, arm in (('truncation', arms.truncation), ('extractive', arms.extractive)):
        first = arm(chunks1, budget)
        carried = arms.carry_text(first) + [{**chunk, 'index': chunk['index'] + 10_000}
                                            for chunk in chunks2]
        second = arm(carried, budget)
        out[name] = {'presented': {1: first['text'], 2: second['text']},
                     'bytes': {1: first['bytes'], 2: second['bytes']}}
    return out


def measure_case(case: dict, out: Path) -> dict:
    root = out / case['case']
    region = flatten(case['items'])
    region2 = flatten(case['items'] + case['round2']['items'])
    region_bytes = len(region.encode())
    budget = max(4096, int(region_bytes * case.get('budget_fraction', DEFAULT_BUDGET_FRACTION)))
    catalog = fact_catalog(case)
    stale_ids = {fact_id for probe in _round_probes(case, 2) for fact_id in probe.get('excludes', [])}

    variants = {
        'wsc': wsc_rounds(case, root / 'wsc', budget),
        'wsc_evidence_only': wsc_rounds(case, root / 'evidence-only', budget, distill=False),
        'wsc_sticky': wsc_rounds(case, root / 'sticky', budget, expiry=False),
    }
    repeat = wsc_rounds(case, out / (case['case'] + '-repeat'), budget)

    materials = {'full_history': {1: region, 2: region2}}
    materials.update({name: value['presented'] for name, value in variants.items()})
    materials.update({name: value['presented'] for name, value in baseline_rounds(case, budget).items()})

    arms_report = {}
    for name, presented in materials.items():
        arms_report[name] = {
            'bytes': {rnd: len(text.encode()) for rnd, text in presented.items()},
            'ratio': {rnd: round(len(text.encode()) / len((region if rnd == 1 else region2).encode()), 4)
                      for rnd, text in presented.items()},
            'budget_ok': {rnd: len(text.encode()) <= budget * 1.05 for rnd, text in presented.items()},
            'probes': {rnd: probe_report(_round_probes(case, rnd), catalog, text)
                       for rnd, text in presented.items()},
            'oracle': {rnd: oracle_report(case, rnd, text) for rnd, text in presented.items()},
            'catalog': {rnd: catalog_report(catalog, text, stale_ids)
                        for rnd, text in presented.items()},
            'fidelity': {rnd: fidelity_profile(region, text)['categories']
                         for rnd, text in presented.items()},
        }
    for name in WSC_ARMS:
        material = variants[name]
        arms_report[name]['reversibility'] = {
            **reversibility(material['package']['items'],
                            material['package'].get('evidence', {}), material['verified']),
            'read_tool_available': True}

    def normalized(text, run_root):
        # The operation directory carries a fresh uuid per stage; it is an
        # address, not content, and must not count as builder variance.
        return re.sub(r'[0-9a-f]{32}', '<OP>', re.sub(re.escape(str(run_root)), '<ROOT>', text))

    digests = {hashlib.sha256(normalized(material, run_root).encode()).hexdigest()
               for material, run_root in ((variants['wsc']['presented'][1], root / 'wsc'),
                                          (repeat['presented'][1], out / (case['case'] + '-repeat')))}
    evidence = variants['wsc']['package'].get('evidence', {})
    ratio = arms_report['wsc']['ratio'][1]
    gate = {'budget_bytes': budget, 'ratio': ratio, 'ratio_ok': ratio <= MAX_RATIO,
            'evidence_exported': len(evidence) > 0,
            'evidence_verified': bool(variants['wsc']['verified']) and all(variants['wsc']['verified'].values()),
            'repeat_stable': len(digests) == 1,
            'arms_in_budget': all(all(ok.values()) for name, value in arms_report.items()
                                  if name != 'full_history' for ok in (value['budget_ok'],))}
    gate['valid'] = bool(gate['ratio_ok'] and gate['evidence_exported'] and gate['evidence_verified']
                         and gate['repeat_stable'] and gate['arms_in_budget'])

    budgeted = [name for name in arms_report if name != 'full_history']
    spread = {rnd: round(max(arms_report[name]['probes'][rnd]['score'] for name in budgeted)
                         - min(arms_report[name]['probes'][rnd]['score'] for name in budgeted), 4)
              for rnd in (1, 2)}
    return {'case': case['case'], 'title': case['title'], 'gate': gate, 'arms': arms_report,
            'spread': spread, 'discriminative': spread[2] >= MIN_SPREAD,
            'comparison': compare(case['case'], arms_report),
            'variance': {'runs': 2, 'distinct_digests': len(digests)},
            'boundary': ('oracle-selector evidence for product arms; probe scoring is mechanical '
                         'presence/absence over decoded material')}


def _metric(arm: dict, key: str) -> float:
    if key == 'probe':
        return arm['probes'][2]['score']
    if key == 'constraint':
        return arm['oracle'][2]['constraint_retention'] or 0.0
    return arm['catalog'][2]['key_recall']


def compare(case_name: str, arms_report: dict) -> dict:
    """Pareto dominance: no worse on quality and no more bytes than the other.

    Equality of ratios is reported for the live matched-ratio gate; dominance
    itself only requires that the winner does not spend more bytes.
    """
    names = [name for name in arms_report if name != 'full_history']
    rows = []
    for left in names:
        for right in names:
            if left == right:
                continue
            a, b = arms_report[left], arms_report[right]
            matched = abs(a['ratio'][1] - b['ratio'][1]) <= RATIO_TOLERANCE
            better = all(_metric(a, key) >= _metric(b, key) for key in ('probe', 'constraint', 'recall'))
            strictly = any(_metric(a, key) > _metric(b, key) for key in ('probe', 'constraint', 'recall'))
            cheaper = a['ratio'][1] < b['ratio'][1] - 0.02
            rows.append({'case': case_name, 'better': left, 'worse': right,
                         'matched_ratio': matched,
                         'dominates': (better and a['ratio'][1] <= b['ratio'][1] + 0.02
                                       and (strictly or cheaper))})
    return {'dominance': rows}


def summary(results: list) -> dict:
    """Aggregate per arm; a dominance win count says who survives comparison."""
    names = list(results[0]['arms']) if results else []
    aggregate = {}
    for name in names:
        cases = [result['arms'][name] for result in results]
        aggregate[name] = {
            'ratio': round(sum(case['ratio'][1] for case in cases) / len(cases), 4),
            'probe_r1': round(sum(case['probes'][1]['score'] for case in cases) / len(cases), 4),
            'probe_r2': round(sum(case['probes'][2]['score'] for case in cases) / len(cases), 4),
            'constraint_r2': round(sum(case['oracle'][2]['constraint_retention'] or 0 for case in cases)
                                   / len(cases), 4),
            'catalog_r2': round(sum(case['catalog'][2]['key_recall'] for case in cases) / len(cases), 4),
            'stale_r2': sum(len(case['probes'][2]['stale_present']) for case in cases),
            'reversible': (all(case['reversibility']['byte_restore'] == 'archive_read_by_source'
                               for case in cases) if 'reversibility' in cases[0] else False),
        }
    wins = {name: 0 for name in names}
    for result in results:
        for row in result['comparison']['dominance']:
            if row['dominates']:
                wins[row['better']] += 1
    return {'arms': aggregate, 'dominance_wins': wins,
            'note': ('live cells stay null: task pass rate, billing, cache hits, retrieval calls and '
                     'constraint violations need host runs; this table is mechanical only')}


def measurements(case_results: list) -> dict:
    rows = []
    for result in case_results:
        if not result['gate']['valid']:
            continue
        wsc = result['arms']['wsc']
        rows.append({'case': result['case'],
                     'a1_delta_pp': None, 'a2_delta_pp': None, 'a3_ratio': None,
                     'b1_recall': wsc['catalog'][2]['key_recall'],
                     'b2_retention': wsc['oracle'][2]['constraint_retention'],
                     'c1_net_saving': None, 'c2_degradation_pp': None,
                     'd1_ratio': None, 'd2_delta_pp': None,
                     'ratio': {'wsc': wsc['ratio'][1], 'native': None, 'window_pp': 1.0},
                     'arms': {'interaction': {'retrieval_calls_native': None,
                                              'retrieval_calls_wsc': None},
                              'constraint_violations': {'native': None, 'wsc': None}}})
    return {'case': 'coding-compaction-v1', 'cases': rows,
            'boundary': 'mechanical columns only; live cells require host runs'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--case', action='append')
    parser.add_argument('--export-measurements', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    out = args.out or Path(tempfile.mkdtemp(prefix='coding-compaction-'))
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for factory in case_module.CASES:
        case = factory()
        if args.case and case['case'] not in args.case:
            continue
        result = measure_case(case, out)
        results.append(result)
        print(f"\n{case['case']}\t比率 {result['gate']['ratio']:.3f}"
              f"\t探针分差 r1 {result['spread'][1]:.2f} / r2 {result['spread'][2]:.2f}"
              f"\t有效 {result['gate']['valid']}\t可区分 {result['discriminative']}")
        print('  臂             比率    探针r1  探针r2  约束r2  目录召回  陈旧泄漏')
        for name, arm in result['arms'].items():
            print(f"  {name:<14} {arm['ratio'][1]:.3f}   {arm['probes'][1]['score']:.2f}"
                  f"    {arm['probes'][2]['score']:.2f}    {arm['oracle'][2]['constraint_retention']:.2f}"
                  f"     {arm['catalog'][2]['key_recall']:.2f}       {len(arm['probes'][2]['stale_present'])}")
    report = {'results': results, 'summary': summary(results),
              'measurements': measurements(results)}
    if args.export_measurements is not None:
        args.export_measurements.write_text(
            json.dumps(report['measurements'], ensure_ascii=False, indent=2), encoding='utf-8')
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('\n汇总（机械指标；真实任务/成本/cache 待宿主实跑）')
        for name, value in report['summary']['arms'].items():
            print(f"  {name:<14} 比率 {value['ratio']:.3f}  探针r2 {value['probe_r2']:.2f}"
                  f"  约束r2 {value['constraint_r2']:.2f}  召回 {value['catalog_r2']:.2f}"
                  f"  陈旧 {value['stale_r2']}  可逆 {value['reversible']}")
        print('  支配胜场:', report['summary']['dominance_wins'])
        print(f"输出目录 {out}\n有效 {sum(r['gate']['valid'] for r in results)}/{len(results)}"
              f"，可区分 {sum(r['discriminative'] for r in results)}/{len(results)}")
    return 0 if all(r['gate']['valid'] and r['discriminative'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
