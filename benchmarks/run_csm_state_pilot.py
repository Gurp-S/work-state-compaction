"""Paired public original-output pilot for the default Bench 2.2 state producer."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import sys

from check_state_contract_cases import CASES, DATA, load_exam, load_histories, load_natural
from csm_bench22 import CsmBench22
from csm_bench22_state_answer import offer_state_answer, publish_state_answer
from bench22 import natural, runner, scoring
from bench22.release import load_items
from bench22.systems import Gateway


class LoggedGateway(Gateway):
    def chat(self, model, messages, phase, tag='', **kw):
        reply = super().chat(model, messages, phase, tag, **kw)
        self.calls.append({'phase': phase, 'tag': tag, 'model': model, 'messages': messages,
                           'options': kw, 'response': reply})
        return reply


def pilot(case, histories, exam, probes, out, run, reuse, separate_producer_budget=False,
          candidate_temporal_state=False, validate_conflict_sources=False, structured_state_answer=False,
          retain_off_day=False):
    is_natural = case in probes
    item = probes[case] if is_natural else exam[case]
    history = histories[item['persona']]
    arms = {}
    path = out / (case.replace('/', '_') + '.json')
    for name, enabled in (('baseline', False), ('state', True)):
        gw = LoggedGateway('http://127.0.0.1:18892/v1', run, f'csm-source:{item["persona"]}:{name}', timeout=40)
        gw.calls = []
        system = CsmBench22(gw, produce_state=enabled, separate_producer_budget=separate_producer_budget,
                            candidate_temporal_state=candidate_temporal_state,
                            validate_conflict_sources=validate_conflict_sources, retain_off_day=retain_off_day)
        cutoff = item['cutoff_turn']
        for turn in history[:cutoff]:
            system.ingest(turn)
        if is_natural:
            assert item['tier'] == 'A'
            system.begin_tail()
            for turn in item.get('tail') or ():
                cutoff += 1
                system.ingest({**turn, 'turn': cutoff})
            now, question = item['probe']['time'], item['probe']['user']
        else:
            now, question = item['now'], item['question']
        ret = system.retrieve(question, now, cutoff, item_id=case)
        assert ret.used_turns and max(ret.used_turns) <= cutoff
        prompt = (natural.answer_prompt(ret.prompt, now, question) if is_natural
                  else ret.prompt + f'\n\n【现在】{now}\n用户：{question}')
        if not enabled and reuse:
            prior = json.loads((reuse / path.name).read_text(encoding='utf-8'))['baseline']
            call = next(row for row in prior['calls'] if row['phase'] == 'answer')
            assert call['messages'] == [{'role': 'user', 'content': prompt}]
            assert prior['used_turns'] == ret.used_turns and prior['cutoff'] == cutoff
            assert call['model'] == runner.ANSWER_MODEL and prior['now'] == now
            arms[name] = prior
            continue
        publication = None
        if enabled and structured_state_answer:
            offered, request = offer_state_answer(question, ret.state_items)
            response = gw.chat(runner.ANSWER_MODEL, [{'role': 'user', 'content': request}], 'answer', case,
                               temperature=0, max_tokens=150, thinking={'type': 'disabled'}) if offered else None
            publication = publish_state_answer(response, offered)
            answer = publication['answer']
        else:
            response = gw.chat(runner.ANSWER_MODEL, [{'role': 'user', 'content': prompt}], 'answer', case,
                               temperature=0, max_tokens=500 if is_natural else 700, thinking={'type': 'disabled'})
            answer = response['choices'][0]['message']['content']
        arms[name] = {'used_turns': ret.used_turns, 'state': ret.state_items, 'answer': answer,
                      'cutoff': cutoff, 'now': now, 'calls': gw.calls}
        if publication is not None:
            arms[name]['publication'] = publication
        # Preserve each arm's original before making the judging call.
        path.write_text(json.dumps(arms, ensure_ascii=False, indent=2), encoding='utf-8')
        if is_natural:
            _, key = natural.load_natural(str(DATA / 'natural'), 'dev')
            judge = natural.judge_turn(gw, item, key[case], [],
                {'time': now, 'user': question, 'answer': answer, 'visible_until': cutoff},
                natural.HistoryIndex(history), case)
            score = natural.turn_score(key[case], judge)
        else:
            rubric = next(row for row in load_items(DATA) if row['id'] == case)
            reply = gw.chat(runner.JUDGE_MODEL,
                            [{'role': 'user', 'content': runner.judge_prompt(rubric, answer)}],
                            'judge', case, temperature=0, max_tokens=700, thinking={'type': 'disabled'})
            judge = runner.parse_json(reply['choices'][0]['message']['content'])
            score = scoring.judge_pass(judge)
        arms[name].update(judge=judge, score=score)
        path.write_text(json.dumps(arms, ensure_ascii=False, indent=2), encoding='utf-8')
    print(case, [(name, arm['score'], [i['kind'] for i in arm['state']]) for name, arm in arms.items()], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--reuse-baseline', type=Path)
    parser.add_argument('--separate-producer-budget', action='store_true')
    parser.add_argument('--candidate-temporal-state', action='store_true')
    parser.add_argument('--validate-conflict-sources', action='store_true')
    parser.add_argument('--structured-state-answer', action='store_true')
    parser.add_argument('--retain-off-day', action='store_true')
    args = parser.parse_args()
    run = args.run
    out = DATA.parent / run
    out.mkdir(exist_ok=False)
    fingerprints = ['benchmarks/csm_bench22.py', 'benchmarks/csm_bench22_state.py',
                    'benchmarks/csm_bench22_producer_budget.py', 'benchmarks/run_csm_state_pilot.py',
                    'benchmarks/csm_bench22_temporal_scope.py', 'benchmarks/csm_bench22_conflict_scope.py',
                    'benchmarks/csm_bench22_state_answer.py',
                    'src/wsc/csm/state_extraction.py', 'src/wsc/csm/state_bundle.py']
    root = DATA.parents[2]
    (out / 'inputs.json').write_text(json.dumps({path: hashlib.sha256(
        (root / path).read_bytes()).hexdigest() for path in fingerprints} | {
            'separate_producer_budget': args.separate_producer_budget,
            'candidate_temporal_state': args.candidate_temporal_state,
            'validate_conflict_sources': args.validate_conflict_sources,
            'structured_state_answer': args.structured_state_answer,
            'retain_off_day': args.retain_off_day}, indent=2), encoding='utf-8')
    histories, exam, probes = load_histories(DATA), load_exam(), load_natural()
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(pilot, case, histories, exam, probes, out, run, args.reuse_baseline,
                            args.separate_producer_budget, args.candidate_temporal_state,
                            args.validate_conflict_sources, args.structured_state_answer, args.retain_off_day)
                for case in CASES]
        for job in jobs:
            job.result()
