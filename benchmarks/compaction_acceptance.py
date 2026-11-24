"""Compaction acceptance: the scoring table as executable code.

Two independent judgments, never merged:

* Table score — the compressed configuration against the full-history baseline
  (A1-A3, B1-B2, C1-C2, D1-D2), with vetoes and the 90/80/70 grade bands.
* Head-to-head gate at matched compression ratio — WSC against DSH native
  compaction. The interaction-cost increment (retrieval calls) and the
  constraint-violation increment must both be <= 0. A higher ratio never
  outranks a positive increment.

Cells that need a live host and model (task runs, pass^k, billing, KV cache
hits, retrieval calls) are explicit ``null``. A report with unmeasured cells is
``insufficient_evidence``; it is never rounded up into a pass.

Mechanical profiling (no model): layered verbatim availability of key facts,
paths, errors, decisions and code; byte-level reversibility of the exported
material; and repeat variance of a deterministic builder.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _pp(value) -> float:
    """Difference in percentage points; accepts 0.60 or 60, but 1 stays 1pp."""
    number = float(value)
    return number * 100.0 if abs(number) < 1.0 else number


# Each item: weight, score(d) -> 0..100, veto(d) -> bool. ``d`` is the case
# aggregate (means over cases unless a single case). Definitions follow the
# acceptance table: positive deltas are losses relative to the full history.
def _a1(d):  # F2P+P2P pass-rate loss, veto > 3pp
    delta = d['a1_delta_pp']
    return 100.0 if delta <= 0 else 100.0 * clamp((3.0 - delta) / 3.0)


def _a2(d):  # operational-constraint compliance loss, veto > 5pp
    delta = d['a2_delta_pp']
    return 100.0 * clamp((5.0 - delta) / 5.0)


def _a3(d):  # safety margin R = production threshold / cliff threshold
    ratio = d['a3_ratio']
    return 100.0 * clamp((ratio - 1.0) / 0.5)


def _b1(d):  # key-state recall (paths, identifiers, failures, repeated detail)
    return 100.0 * min(1.0, d['b1_recall'] / 0.85)


def _b2(d):  # constraint/rule retention after the Nth compaction
    return 100.0 * min(1.0, d['b2_retention'] / 0.80)


def _c1(d):  # net saving including compressor cost and cache degradation
    return 100.0 * clamp(d['c1_net_saving'] / 0.10)


def _c2(d):  # KV cache hit-rate degradation, in pp
    return 100.0 * clamp((10.0 - d['c2_degradation_pp']) / 10.0)


def _d1(d):  # pass^k retention ratio
    return 100.0 * clamp((d['d1_ratio'] - 0.90) / 0.05)


def _d2(d):  # pass^k absolute loss, in pp
    return 100.0 * clamp((5.0 - d['d2_delta_pp']) / 5.0)


ITEMS = [
    {'id': 'A1', 'name': '任务有效性：F2P+P2P 通过率 Δ', 'weight': 20,
     'field': 'a1_delta_pp', 'score': _a1, 'veto': lambda d: d['a1_delta_pp'] > 3.0,
     'veto_text': 'Δ>3pp'},
    {'id': 'A2', 'name': '操作性约束遵守率 Δ', 'weight': 10,
     'field': 'a2_delta_pp', 'score': _a2, 'veto': lambda d: d['a2_delta_pp'] > 5.0,
     'veto_text': 'Δ>5pp'},
    {'id': 'A3', 'name': '阈值安全余量 R', 'weight': 5,
     'field': 'a3_ratio', 'score': _a3, 'veto': lambda d: d['a3_ratio'] < 1.1,
     'veto_text': 'R<1.1'},
    {'id': 'B1', 'name': '关键状态召回率', 'weight': 15,
     'field': 'b1_recall', 'score': _b1, 'veto': lambda d: d['b1_recall'] < 0.70,
     'veto_text': '<70%'},
    {'id': 'B2', 'name': '约束/规则保留率', 'weight': 10,
     'field': 'b2_retention', 'score': _b2, 'veto': lambda d: d['b2_retention'] < 0.70,
     'veto_text': '<70%'},
    {'id': 'C1', 'name': '净成本节省率', 'weight': 12,
     'field': 'c1_net_saving', 'score': _c1, 'veto': lambda d: d['c1_net_saving'] <= 0.0,
     'veto_text': '≤0'},
    {'id': 'C2', 'name': 'KV Cache 命中率退化', 'weight': 8,
     'field': 'c2_degradation_pp', 'score': _c2, 'veto': None, 'veto_text': ''},
    {'id': 'D1', 'name': 'pass^k 保持率', 'weight': 12,
     'field': 'd1_ratio', 'score': _d1, 'veto': lambda d: d['d1_ratio'] < 0.90,
     'veto_text': '<0.90'},
    {'id': 'D2', 'name': 'pass^k 绝对下降 Δ', 'weight': 8,
     'field': 'd2_delta_pp', 'score': _d2, 'veto': lambda d: d['d2_delta_pp'] > 5.0,
     'veto_text': 'Δ>5pp'},
]

GRADES = [(90.0, '优秀', '可上线，常规监控'),
          (80.0, '通过', '可上线，重点监控约束遵守与 cache 命中率'),
          (70.0, '有条件整改', '不得直接上线，需针对低分项复测或调阈值'),
          (0.0, '不通过', '压缩代价不可接受，回退或重设计')]


def _aggregate(raw: dict) -> dict:
    """Mean the per-case values. A cell is measured only if every case has it."""
    cases = raw['cases']
    pp_fields = {'a1_delta_pp', 'a2_delta_pp', 'c2_degradation_pp', 'd2_delta_pp'}
    out = {}
    for item in ITEMS:
        field = item['field']
        values = [case.get(field) for case in cases]
        if values and all(v is not None for v in values):
            mean = sum(float(v) for v in values) / len(values)
            out[field] = _pp(mean) if field in pp_fields else mean
        else:
            out[field] = None
    return out


def evaluate(measurements: dict) -> dict:
    """Score the table and the matched-ratio gates from a measurements file.

    The file is ``{"cases": [...]}``; each case carries already-computed arm
    values so this function never invents or re-derives a cost or a ratio.
    """
    cases = measurements['cases']
    for case in cases:
        assert 'case' in case and 'arms' in case, 'measurement_case_invalid'
    aggregates = _aggregate(measurements)

    items, vetoes = [], []
    total = 0.0
    measured_weight = 0
    for item in ITEMS:
        value = aggregates[item['field']]
        if value is None:
            items.append({**{k: item[k] for k in ('id', 'name', 'weight')},
                          'value': None, 'score': None, 'weighted': None,
                          'veto': None, 'measured': False})
            continue
        score = round(item['score'](aggregates), 2)
        weighted = round(score * item['weight'] / 100.0, 2)
        triggered = item['veto'] is not None and item['veto'](aggregates)
        if triggered:
            vetoes.append({'id': item['id'], 'rule': item['veto_text']})
        measured_weight += item['weight']
        total += weighted
        items.append({**{k: item[k] for k in ('id', 'name', 'weight')},
                      'value': value, 'score': score, 'weighted': weighted,
                      'veto': triggered, 'measured': True})
    total = round(total, 2)

    # Head-to-head at matched ratio: per case, WSC minus native. Both deltas
    # must be <= 0 in every matched case; an unmatched case cannot be compared.
    gates = []
    for case in cases:
        ratio = case.get('ratio') or {}
        window = float(ratio.get('window_pp', 1.0))
        matched = (ratio.get('wsc') is not None and ratio.get('native') is not None
                   and abs(_pp(ratio['wsc']) - _pp(ratio['native'])) <= window)
        interaction = case['arms'].get('interaction') or {}
        violations = case['arms'].get('constraint_violations') or {}
        retrieval = (None if interaction.get('retrieval_calls_wsc') is None
                     or interaction.get('retrieval_calls_native') is None else
                     interaction['retrieval_calls_wsc'] - interaction['retrieval_calls_native'])
        violation = (None if violations.get('wsc') is None or violations.get('native') is None
                     else violations['wsc'] - violations['native'])
        gates.append({'case': case['case'], 'matched': matched,
                      'retrieval_delta': retrieval, 'violation_delta': violation,
                      'retrieval_ok': None if retrieval is None else retrieval <= 0,
                      'violation_ok': None if violation is None else violation <= 0})

    measured_gates = [g for g in gates if g['matched']]
    def mean_delta(key):
        values = [g[key] for g in measured_gates if g[key] is not None]
        return sum(values) / len(values) if values else None
    head = {
        'matched_cases': len(measured_gates),
        'unmatched_cases': len(gates) - len(measured_gates),
        'retrieval_delta': mean_delta('retrieval_delta'),
        'violation_delta': mean_delta('violation_delta'),
        'retrieval_ok': all(g['retrieval_ok'] is True for g in measured_gates) if measured_gates else None,
        'violation_ok': all(g['violation_ok'] is True for g in measured_gates) if measured_gates else None,
        'per_case': gates,
    }
    head['pass'] = (None if not measured_gates else
                    bool(head['retrieval_ok'] and head['violation_ok']))

    if vetoes:
        verdict = ('不通过', '否决项触发：' + '、'.join(v['id'] + '(' + v['rule'] + ')' for v in vetoes))
    elif measured_weight < 100:
        verdict = ('证据不足', f'未采集权重 {100 - measured_weight}；不得据此判定')
    elif total >= 90.0:
        verdict = ('优秀', GRADES[0][2])
    elif total >= 80.0:
        verdict = ('通过', GRADES[1][2])
    elif total >= 70.0:
        verdict = ('有条件整改', GRADES[2][2])
    else:
        verdict = ('不通过', GRADES[3][2])

    return {
        'case': measurements.get('case'),
        'matched_ratio': [{'case': case['case'], 'ratio': case.get('ratio')} for case in cases],
        'items': items,
        'weighted_total': total,
        'measured_weight': measured_weight,
        'vetoes': vetoes,
        'grade': verdict[0],
        'grade_reason': verdict[1],
        'head_to_head': head,
        'final': (None if head['pass'] is None or verdict[0] not in ('优秀', '通过')
                  else ('压缩器不劣于原生' if head['pass'] else '压缩器不更好')),
        'boundary': measurements.get('boundary'),
    }


def render(report: dict) -> str:
    lines = ['项目\t数值/结论']
    lines.append(f"加权总分\t{report['weighted_total'] if report['measured_weight'] == 100 else '（未采集完整）'}"
                 f"\t已采集权重 {report['measured_weight']}/100")
    lines.append(f"总分等级\t{report['grade']}\t{report['grade_reason']}")
    lines.append('否决项\t' + ('无' if not report['vetoes'] else
                 '、'.join(v['id'] + '(' + v['rule'] + ')' for v in report['vetoes'])))
    head = report['head_to_head']
    lines.append(f"匹配比头对头\t牵引差 Δ{head['retrieval_ok']}\t违例差 Δ{head['violation_ok']}"
                 f"\t匹配用例 {head['matched_cases']}，未匹配 {head['unmatched_cases']}")
    if report['final'] is not None:
        lines.append(f"最终判定\t{report['grade']}：{report['final']}")
    lines.append('')
    lines.append('编号\t指标\t实际\t单项得分\t加权')
    for item in report['items']:
        value = '未采集' if not item['measured'] else f"{item['value']:.4g}"
        score = '—' if not item['measured'] else f"{item['score']:.2f}"
        weighted = '—' if item['weighted'] is None else f"{item['weighted']:.2f}"
        veto = ' [否决]' if item['veto'] else ''
        lines.append(f"{item['id']}\t{item['name']}\t{value}\t{score}{veto}\t{weighted}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Mechanical profile: what can be proven without a model.
# ---------------------------------------------------------------------------
SIGNALS = {
    'paths': re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)'),
    'identifiers': re.compile(r'`([^`\n]{2,80})`|[A-Za-z_][A-Za-z0-9_]{5,}'),
    'errors': re.compile(r'(?im)^.*\b(?:error|exception|traceback|failed|panic)\b.*$'),
    'decisions': re.compile(r'(?i)\b(?:decided|decision|chose|choose|will use|adopt|决定|采用|改为|选择)\b'),
    'constraints': re.compile(r'(?i)\b(?:must|must not|do not|never|required|不得|必须|禁止|保留|约束)\b'),
    'code': re.compile(r'(?m)^\s*(?:def |class |function |const |let |var |import |from |#include|public |private |async function )'),
}


def signals(text: str) -> dict:
    out = {}
    for name, pattern in SIGNALS.items():
        found = set()
        if name in ('decisions', 'constraints', 'errors', 'code'):
            lines = [line.strip() for line in str(text or '').splitlines()]
            found = {line[:200] for line in lines if line and pattern.search(line)}
        else:
            found = set()
            for match in pattern.finditer(str(text or '')):
                value = match.group(1) if pattern.groups and match.group(1) else match.group(0)
                found.add(value)
        out[name] = {value for value in found if 3 <= len(value) <= 200}
    return out


def fidelity_profile(region_text: str, presented_text: str) -> dict:
    """Verbatim availability of key material in the presented checkpoint.

    This is a precondition of model recall, not recall itself: it proves the
    exact bytes are present for the later model to use.
    """
    expected = signals(region_text)
    present = signals(presented_text)
    categories = {}
    total = retained = 0
    for name, values in expected.items():
        hit = len(values & present[name])
        categories[name] = {'expected': len(values), 'retained': hit,
                            'rate': round(hit / len(values), 4) if values else None,
                            'missing': sorted(values - present[name])[:8]}
        total += len(values)
        retained += hit
    return {'categories': categories, 'retained': retained, 'expected': total,
            'rate': round(retained / total, 4) if total else None,
            'kind': 'verbatim_availability_not_semantic_recall'}


def reversibility(items: list, evidence: dict | None = None, verified: dict | None = None) -> dict:
    """Whether dropped bytes can be restored, and through what material.

    WSC exports every source; ``verified`` maps source id -> True when the
    exported object matched its digest at read time. Native summaries carry
    opaque items with no byte-level restore path in the presented material.
    """
    opaque = sum(1 for item in items or [] if item.get('type') in ('compaction', 'reasoning'))
    evidence = evidence or {}
    verified = verified or {}
    ok = [key for key, value in verified.items() if value]
    return {
        'opaque_items': opaque,
        'evidence_locators': len(evidence),
        'verified_locators': len(ok),
        'byte_restore': ('archive_read_by_source' if evidence and len(ok) == len(evidence)
                         else 'partial' if evidence else 'not_exposed'),
        'trigger': ('host read tool on evidence locator' if evidence else
                    'none (opaque summary only)'),
    }


def repeat_variance(build, n: int = 3) -> dict:
    """Byte-level variance of repeated builds from one identical input."""
    values = [build() for _ in range(n)]
    texts = [value['text'] if isinstance(value, dict) else str(value) for value in values]
    digests = sorted({__import__('hashlib').sha256(text.encode()).hexdigest() for text in texts})
    return {'runs': n, 'distinct_digests': len(digests),
            'max_bytes_delta': max(map(len, texts)) - min(map(len, texts)),
            'varies': len(digests) > 1}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements', type=Path, help='measurements JSON to score')
    parser.add_argument('--region', type=Path, help='source region text for the profile')
    parser.add_argument('--checkpoint', type=Path, help='presented checkpoint text')
    parser.add_argument('--items', type=Path, help='checkpoint items JSON for reversibility')
    parser.add_argument('--evidence', type=Path, help='evidence locators JSON')
    parser.add_argument('--json', action='store_true', help='emit JSON instead of a table')
    args = parser.parse_args(argv)
    if args.measurements is not None:
        value = evaluate(json.loads(args.measurements.read_text(encoding='utf-8')))
        print(json.dumps(value, ensure_ascii=False, indent=2) if args.json else render(value))
        return 0
    if args.region is not None and args.checkpoint is not None:
        result = {'profile': fidelity_profile(args.region.read_text(encoding='utf-8'),
                                              args.checkpoint.read_text(encoding='utf-8'))}
        if args.items is not None:
            result['reversibility'] = reversibility(
                json.loads(args.items.read_text(encoding='utf-8')),
                json.loads(args.evidence.read_text(encoding='utf-8')) if args.evidence else None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
