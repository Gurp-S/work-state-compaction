"""Engine-owned literals and gated distillation, independent of the eval harness."""
import json
import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src')]

from wsc.contracts import Event
from wsc.coding_ledger import merge_engine_values, terms_of, value_rows
from wsc.distillation_gate import high_signal, instruction, should_distil
from wsc.resume_contract import RESUME_CONTRACT_V2, resume_contract


def call(call_id, name, **args):
    return Event(id='c-' + call_id, kind='call', call_id=call_id,
                 payload={'name': name, 'arguments': json.dumps(args)})


def result(call_id, text, ordinal=0):
    return Event(id=f'r-{call_id}', kind='result', call_id=call_id, text=text, payload={})


class ValueLedger(TestCase):
    def setUp(self):
        self.events = [
            call('r1', 'read', file_path='src/limits.py'),
            result('r1', 'capacity table\ncapacity limit is LIM4 requests per minute'),
            call('t1', 'pwsh', command='python -m unittest tests.test_limits'),
            result('t1', 'PASS tests.test_limits\nok 1 passed in 0.3s'),
            call('r2', 'read', file_path='docs/note.md'),
            result('r2', 'background note: routine context without values.'),
            call('r3', 'pwsh', command='cache get region'),
            result('r3', 'cache hit (written 2025-01-01): region code STL8'),
            call('r4', 'read', file_path='src/limits.py'),
            result('r4', 'capacity table\ncapacity limit is LIM4 requests per minute'),
            call('e1', 'pwsh', command='read src/limits.py'),
            result('e1', 'Error: timeout after 10s'),
        ]

    def test_value_rows_are_stable_and_identifying(self):
        rows = value_rows(self.events)
        self.assertEqual([row['key'] for row in rows], ['V1', 'V2'])
        self.assertTrue(rows[0]['label'].startswith('src/limits.py:'))
        self.assertIn('LIM4', rows[0]['terms'])
        self.assertIn('STL8', rows[1]['terms'])
        self.assertEqual(len({row['source_id'] for row in rows}), 2)

    def test_value_rows_skip_tests_errors_filler_and_duplicates(self):
        texts = [row['text'] for row in value_rows(self.events)]
        self.assertFalse(any('PASS' in text or 'Error' in text or 'routine' in text
                             for text in texts))
        self.assertEqual(sum('LIM4' in text for text in texts), 1)

    def test_merge_hides_only_restated_values(self):
        values = value_rows(self.events)
        entries = [
            {'kind': 'fact', 'text': 'src/limits.py: capacity = LIM4'},
            {'kind': 'decision', 'text': 'decision: cap requests at the table value'},
            {'kind': 'fact', 'text': 'retries = 7'},
        ]
        shown = [entry['text'] for entry in merge_engine_values(entries, values)]
        self.assertNotIn('src/limits.py: capacity = LIM4', shown)
        self.assertIn('decision: cap requests at the table value', shown)
        self.assertIn('retries = 7', shown)

    def test_terms_keep_literals_and_drop_encoded_punctuation(self):
        self.assertIn('src/x.py', terms_of('open src/x.py then run it'))
        self.assertFalse(any('"' in term or '\\' in term
                             for term in terms_of('python -m unittest tests.test_io\\"}')))


class Gate(TestCase):
    def delta(self, *items):
        return list(items)

    def test_instruction_and_continue(self):
        self.assertTrue(instruction(self.delta(
            {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text', 'text': 'Change: export must be async.'}]})))
        self.assertFalse(instruction(self.delta(
            {'type': 'message', 'role': 'user',
             'content': [{'type': 'input_text', 'text': 'Continue.'}]})))

    def test_high_signal_failure_and_recorded_decision(self):
        failure = {'type': 'function_call_output',
                   'output': 'FAILED tests.test_retry - AssertionError: missing key'}
        decision = {'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text',
                                 'text': 'Root cause is src/retry.py; switch to send_once.'}]}
        self.assertTrue(high_signal(self.delta(failure)))
        self.assertTrue(high_signal(self.delta(decision)))
        self.assertFalse(high_signal(self.delta(
            {'type': 'function_call_output', 'output': 'ok 1 passed'})))

    def test_cooldown_bounds_high_signal_calls(self):
        failure = {'type': 'function_call_output', 'output': 'Error: timeout'}
        self.assertTrue(should_distil(self.delta(failure), round_number=1))
        self.assertTrue(should_distil(self.delta(failure), round_number=2,
                                      last_signal=0, cooldown=2))
        self.assertFalse(should_distil(self.delta(failure), round_number=3,
                                       last_signal=2, cooldown=2))
        self.assertTrue(should_distil(self.delta(failure), round_number=4,
                                      last_signal=2, cooldown=2))
        self.assertTrue(should_distil(
            self.delta({'type': 'message', 'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'Change: use B.'}]}),
            round_number=3, last_signal=2, cooldown=5))

    def test_resume_contract_names_values_and_batching(self):
        self.assertIn('Observed values', RESUME_CONTRACT_V2)
        self.assertIn('one turn', RESUME_CONTRACT_V2)
        self.assertIn('never use it', RESUME_CONTRACT_V2)

    def test_value_rules_only_when_checkpoint_has_values(self):
        with_values = resume_contract(True)
        without = resume_contract(False)
        self.assertIn('Observed values', with_values)
        self.assertNotIn('Observed values', without)
        self.assertNotIn('recover a value', without)
        for text in (with_values, without):
            self.assertIn('one turn', text)
            self.assertIn('first turn', text)
            self.assertIn('never use it', text)


if __name__ == '__main__':
    main()
