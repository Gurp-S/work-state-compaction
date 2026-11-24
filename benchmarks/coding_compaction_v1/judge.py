"""LLM-as-judge over a resume run: anonymized letters, fixed rubric, no arm labels.

The mechanical oracle in resume.py stays primary; this judge adds a qualitative
ranking over the same checkpoints and emitted actions. Use a different judge
model when available (WSC_JUDGE_MODEL); otherwise the same endpoint judges its
own family and that bias is recorded in the output.

    python benchmarks/coding_compaction_v1/judge.py --run <resume-run-dir>
    python benchmarks/coding_compaction_v1/judge.py --self-check
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from coding_compaction_v1 import live  # noqa: E402
from coding_compaction_v1 import resume_cases  # noqa: E402

LETTERS = ('A', 'B', 'C', 'D')
CRITERIA = ('continuity', 'grounding', 'constraint', 'economy', 'overall')

PROMPT = '\n'.join([
    'You evaluate resumed coding agents. Several responses answer the same scenario,',
    'shown under anonymized letters. Each checkpoint is the ONLY state that agent had;',
    'the actions are what it chose to do next.',
    '',
    'Score each criterion 0-2, where 2 is clearly correct, 1 is partially or ambiguously correct,',
    '0 is wrong or unsupported:',
    '- continuity: acts on the current task, on the right file and in a sensible order.',
    '- grounding: exact values, tokens, paths and commands are supported by the checkpoint or by fetched evidence.',
    '  A plausible guess of an exact value scores 0 even if it happens to match.',
    '- constraint: respects the currently effective requirements; no contradiction with a later change.',
    '- economy: no unnecessary runs, reads or fetches for the information already present.',
    '- overall: the quality of this continuation, not the length or polish of the prose.',
    '',
    'Do not reward verbosity. Do not infer facts the checkpoint does not establish.',
    'A fetch whose key appears in the checkpoint evidence index is a valid grounding path:',
    'do not score it 0 because the fetched value is not repeated in the checkpoint.',
    'An engine record beside a response states whether a fetch was honored and whether it',
    'returned the exact value; treat a successful fetch as grounding.',
    'A longer checkpoint is not better grounded; score only the exact values the continuation relies on.',
    'For constraints, compare against the verbatim requirements listed below; where a later',
    'round changes a requirement, the later one is effective.',
    'Score and rank exactly the letters shown below, and no others.',
    'Return only a JSON object of the shape given at the end.',
])


def shape(letters):
    scores = ','.join(f'"{letter}":{{"continuity":0,"grounding":0,"constraint":0,'
                      f'"economy":0,"overall":0}}' for letter in letters)
    ranking = ','.join(f'"{letter}"' for letter in letters)
    reasons = ','.join(f'"{letter}":"<=20 words"' for letter in letters)
    return f'{{"scores":{{{scores}}},"ranking":[{ranking}],"reasons":{{{reasons}}}}}'


def cases_by_name():
    factories = list(resume_cases.CASES) + list(resume_cases.LONG_CASES)
    return {factory()['case']: factory for factory in factories}


def describe(case):
    lines = [f"Scenario: {case['case']}"]
    rounds = case.get('rounds') or [case['items']]
    requirements = []
    for number, delta in enumerate(rounds, 1):
        for item in delta:
            if item.get('type') == 'message' and item.get('role') == 'user':
                text = ' '.join((live.item_text(item) or '').split())
                if text:
                    requirements.append(f'[round {number}] {text}')
    if requirements:
        joined = ' | '.join(requirements)
        lines.append('User requirements (verbatim, in order, latest wins): ' + joined[:900])
    lines.append('Required next actions (ground truth): ' + json.dumps(case['required']))
    if case.get('forbidden'):
        lines.append('Forbidden actions: ' + json.dumps(case['forbidden']))
    if case.get('secret'):
        lines.append('Exact value the task depends on: ' + case['secret'])
    if case.get('files'):
        lines.append('Files readable by the agent: ' + ', '.join(sorted(case['files'])))
    return '\n'.join(lines)


def judge_prompt(case, blocks, letters=None):
    letters = list(letters or [letter for letter, _, *_ in blocks])
    parts = [PROMPT, '', describe(case), '']
    for block in blocks:
        letter, checkpoint, actions = block[:3]
        meta = block[3] if len(block) > 3 else None
        parts.append(f'### Response {letter}')
        parts.append('Checkpoint:')
        parts.append(checkpoint)
        parts.append('Actions:')
        parts.append(json.dumps(actions, ensure_ascii=False))
        if meta:
            parts.append('Engine record: ' + json.dumps(meta, ensure_ascii=False))
        parts.append('')
    parts.append('Return exactly this shape:')
    parts.append(shape(letters))
    return '\n'.join(parts)


def valid(parsed, letters=None):
    if not isinstance(parsed, dict):
        return False
    scores, ranking = parsed.get('scores'), parsed.get('ranking')
    if not isinstance(scores, dict) or not isinstance(ranking, list):
        return False
    expected = set(letters if letters is not None else scores)
    if not expected or set(scores) != expected:
        return False
    if sorted(ranking) != sorted(expected):
        return False
    return all(isinstance(scores[letter], dict)
               and all(isinstance(scores[letter].get(name), int)
                       and 0 <= scores[letter][name] <= 2 for name in CRITERIA)
               for letter in expected)


def judge_case(model, case, blocks, label, letters):
    prompt = judge_prompt(case, blocks, letters)
    output = model.chat([{'role': 'user', 'content': prompt}], max_tokens=8192, label=label)
    parsed = live.json_object(output['text'])
    if not valid(parsed, letters):
        parsed = live.json_object(model.chat([
            {'role': 'user', 'content': prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object with the letters shown '
                                       'and a full ranking.'},
        ], max_tokens=8192, label=label + '-retry')['text'])
    if not valid(parsed, letters):
        raise ValueError(f'judge_output_invalid: {output["text"][:200]}')
    return parsed


def run(run_dir, model, seed=0):
    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    factories = cases_by_name()
    mapping, judgements = {}, []
    for report in summary['results']:
        case = factories[report['case']]()
        arms = list(report['arms'])
        letters = list(LETTERS[:len(arms)])
        random.Random(f"{report['case']}:{seed}").shuffle(letters)
        mapping[report['case']] = dict(zip(arms, letters))
        blocks = []
        for arm in arms:
            checkpoint = (run_dir / report['case'] / f'checkpoint-{arm}.txt').read_text(encoding='utf-8')
            row = report['arms'][arm]
            meta = {key: row.get(key) for key in ('fetched', 'fetch_hit', 'grounded')
                    if row.get(key) is not None}
            blocks.append((mapping[report['case']][arm], checkpoint,
                           row.get('actions', []), meta))
        blocks.sort(key=lambda item: item[0])
        parsed = judge_case(model, case, blocks, f'judge:{report["case"]}', letters)
        letter_to_arm = {letter: arm for arm, letter in mapping[report['case']].items()}
        row = {'case': report['case'], 'mapping': mapping[report['case']],
               'scores': {letter_to_arm[letter]: value for letter, value in parsed['scores'].items()},
               'ranking': [letter_to_arm[letter] for letter in parsed['ranking']],
               'reasons': {letter_to_arm[letter]: text for letter, text in
                           (parsed.get('reasons') or {}).items()}}
        judgements.append(row)
        print(f"\n{report['case']}  ranking {row['ranking']}")
        for arm in arms:
            scores = row['scores'][arm]
            print(f"  {arm:<11} overall {scores['overall']}  "
                  + ' '.join(f"{name} {scores[name]}" for name in CRITERIA[:-1]))
    arms = sorted({arm for row in judgements for arm in row['scores']})
    summary_scores = {}
    for arm in arms:
        rows = [row['scores'][arm] for row in judgements]
        summary_scores[arm] = {name: round(sum(row[name] for row in rows) / len(rows), 3)
                               for name in CRITERIA}
        summary_scores[arm]['wins'] = sum(row['ranking'] and row['ranking'][0] == arm
                                          for row in judgements)
        summary_scores[arm]['top2'] = sum(arm in row['ranking'][:2] for row in judgements)
    print('\nmean scores')
    for arm in arms:
        row = summary_scores[arm]
        print(f"  {arm:<11} overall {row['overall']:.2f}  wins {row['wins']}  top2 {row['top2']}  "
              + ' '.join(f"{name} {row[name]:.2f}" for name in CRITERIA[:-1]))
    payload = {'judge_model': model.name, 'self_judge': model.name == live.MODEL,
               'seed': seed, 'scenarios': judgements, 'mean': summary_scores}
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', model.name)
    suffix = f'-s{seed}' if seed else ''
    target = run_dir / f'judge-{safe}{suffix}.json'
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\noutput', target)
    return payload


def self_check():
    parsed = {'scores': {letter: {name: 1 for name in CRITERIA} for letter in LETTERS},
              'ranking': ['B', 'A', 'C', 'D'], 'reasons': {letter: 'ok' for letter in LETTERS}}
    assert valid(parsed)
    parsed['ranking'] = ['B', 'B', 'C', 'D']
    assert not valid(parsed)
    parsed['ranking'] = ['B', 'A', 'C', 'D']
    parsed['scores']['A']['overall'] = 2.5
    assert not valid(parsed)
    parsed['scores']['A']['overall'] = 1
    three = {'scores': {letter: {name: 1 for name in CRITERIA} for letter in 'ABC'},
             'ranking': ['B', 'A', 'C'], 'reasons': {letter: 'ok' for letter in 'ABC'}}
    assert valid(three, ('A', 'B', 'C'))
    assert not valid(three, LETTERS)
    print('judge self-check ok')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    run_dir = args.run
    if run_dir is None:
        runs = sorted((ROOT / 'benchmarks' / 'coding_compaction_v1' / 'runs').glob('resume-*'))
        if not runs:
            raise SystemExit('no resume run found')
        run_dir = runs[-1]
    name = os.environ.get('WSC_JUDGE_MODEL', live.MODEL)
    model = live.Model(live.load_key(), name=name)
    run(run_dir, model, args.seed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
