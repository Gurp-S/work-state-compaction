"""Targeted contract check on previously failed CSM cases.

No model calls.  It replays the exact history prefix for each case and asserts
that the adapter returns a StateRetrieval with state items first and evidence
separate.  A missing memory state is explicit (NO_CONFIRMED_STATE), never hidden
behind a clock-only prompt.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.local/bench22-public-20261111/dataset'
sys.path[:0] = [str(ROOT / 'benchmarks'), str(ROOT / 'src'),
                str(ROOT / '.bench/chat-memory-benchmark-2.2/benchmark-2.2/harness')]
from bench22.release import load_histories  # noqa: E402
from csm_bench22 import CsmBench22, StateRetrieval  # noqa: E402

CASES = ['M01-G059/s1', 'M01-G146/a', 'M02-F20/f', 'M02-G187/e',
         'NAT-M01-X3-03', 'NAT-M01-H3-02']


def load_exam():
    rows = [json.loads(line) for line in (DATA / 'exam-inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    return {row['id']: row for row in rows}


def load_natural():
    rows = [json.loads(line) for line in (DATA / 'natural/natural-probes-dev.jsonl').read_text(encoding='utf-8').splitlines()]
    return {row['id']: row for row in rows}


def run_case(case_id, histories, exam, natural):
    system = CsmBench22(None)
    if case_id in exam:
        item = exam[case_id]
        turns = histories[item['persona']][:item['cutoff_turn']]
        for turn in turns:
            system.ingest(turn)
        result = system.retrieve(item['question'], item['now'], item['cutoff_turn'])
    else:
        item = natural[case_id]
        turns = histories[item['persona']][:item['cutoff_turn']]
        for turn in turns:
            system.ingest(turn)
        system.begin_tail()
        seq = item['cutoff_turn']
        for turn in item.get('tail') or []:
            seq += 1
            system.ingest({**turn, 'turn': seq})
        result = system.retrieve(item['probe']['user'], item['probe']['time'], seq)
    assert isinstance(result, StateRetrieval), case_id
    kinds = [item['kind'] for item in result.state_items]
    assert len(kinds) >= 2 and kinds[0] == 'CLOCK', case_id
    assert result.prompt.startswith(result.state_text), case_id
    assert '【聊天记录】' not in result.state_text, case_id
    reason = None
    if 'NO_CONFIRMED_STATE' in kinds:
        assert kinds == ['CLOCK', 'NO_CONFIRMED_STATE'], case_id
        reason = result.state_items[1].get('reason')
        assert reason, case_id
    return {
        'id': case_id,
        'state_kinds': kinds,
        'no_confirmed_state_reason': reason,
        'state_chars': len(result.state_text),
        'evidence_chars': len(result.evidence),
        'used_turns': len(result.used_turns),
    }


if __name__ == '__main__':
    histories = load_histories(DATA)
    exam, natural = load_exam(), load_natural()
    rows = [run_case(case, histories, exam, natural) for case in CASES]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    missing = sum(row['no_confirmed_state_reason'] is not None for row in rows)
    print(f'contract-ok {len(rows)}; state-present {len(rows) - missing}; no-confirmed-state {missing}')
