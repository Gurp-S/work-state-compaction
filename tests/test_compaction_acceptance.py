"""The acceptance table's sample numbers are pinned as tests, not prose."""
import json
import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks'))
from compaction_acceptance import (evaluate, fidelity_profile, repeat_variance,
                                   reversibility, render)


def example(**over):
    case = {
        'case': 'example',
        'a1_delta_pp': 1.0, 'a2_delta_pp': 2.0, 'a3_ratio': 1.6,
        'b1_recall': 0.78, 'b2_retention': 0.82,
        'c1_net_saving': 0.07, 'c2_degradation_pp': 6.0,
        'd1_ratio': 0.92, 'd2_delta_pp': 4.0,
        'ratio': {'native': 0.30, 'wsc': 0.305, 'window_pp': 1.0},
        'arms': {'interaction': {'retrieval_calls_native': 10, 'retrieval_calls_wsc': 12},
                 'constraint_violations': {'native': 1, 'wsc': 2}},
    }
    case.update(over)
    return {'case': 'example', 'cases': [case],
            'boundary': 'synthetic sample from the acceptance template; not a real run'}


class AcceptanceScoring(TestCase):
    def test_sample_numbers_reproduce_the_published_scores(self):
        report = evaluate(example())
        scores = {item['id']: item['score'] for item in report['items']}
        self.assertEqual(scores, {'A1': 66.67, 'A2': 60.0, 'A3': 100.0, 'B1': 91.76,
                                  'B2': 100.0, 'C1': 70.0, 'C2': 40.0, 'D1': 40.0, 'D2': 20.0})
        self.assertEqual(report['weighted_total'], 66.09)
        self.assertEqual(report['measured_weight'], 100)
        self.assertEqual(report['vetoes'], [])
        self.assertEqual(report['grade'], '不通过')

    def test_a_veto_fails_the_run_even_with_a_high_total(self):
        report = evaluate(example(a1_delta_pp=4.0))
        self.assertEqual(report['vetoes'], [{'id': 'A1', 'rule': 'Δ>3pp'}])
        self.assertEqual(report['grade'], '不通过')
        self.assertIn('A1(Δ>3pp)', report['grade_reason'])

    def test_unmeasured_cells_are_insufficient_evidence_not_a_failure(self):
        report = evaluate(example(d1_ratio=None, d2_delta_pp=None))
        self.assertEqual(report['measured_weight'], 80)
        self.assertEqual(report['grade'], '证据不足')
        unmeasured = [item['id'] for item in report['items'] if not item['measured']]
        self.assertEqual(unmeasured, ['D1', 'D2'])

    def test_matched_ratio_gate_requires_both_increments_non_positive(self):
        report = evaluate(example())
        head = report['head_to_head']
        self.assertTrue(head['matched_cases'] == 1)
        self.assertEqual(head['retrieval_delta'], 2)
        self.assertEqual(head['violation_delta'], 1)
        self.assertFalse(head['retrieval_ok'])
        self.assertFalse(head['pass'])
        self.assertIsNone(report['final'], 'a failing table never claims head-to-head superiority')

        better = evaluate(example(
            arms={'interaction': {'retrieval_calls_native': 10, 'retrieval_calls_wsc': 10},
                  'constraint_violations': {'native': 1, 'wsc': 1}},
            a1_delta_pp=0.0, a2_delta_pp=0.0, a3_ratio=1.6, b1_recall=0.90,
            b2_retention=0.90, c1_net_saving=0.12, c2_degradation_pp=2.0,
            d1_ratio=0.97, d2_delta_pp=1.0))
        self.assertTrue(better['head_to_head']['pass'])
        self.assertEqual(better['grade'], '优秀')
        self.assertEqual(better['final'], '压缩器不劣于原生')

    def test_unmatched_ratio_cannot_be_compared(self):
        report = evaluate(example(ratio={'native': 0.30, 'wsc': 0.40, 'window_pp': 1.0}))
        self.assertEqual(report['head_to_head']['matched_cases'], 0)
        self.assertIsNone(report['head_to_head']['pass'])
        self.assertIsNone(report['final'])

    def test_percent_points_accept_both_fractions_and_points(self):
        as_points = evaluate(example(a1_delta_pp=1.0))
        as_fractions = evaluate(example(a1_delta_pp=0.01))
        self.assertEqual(as_points['weighted_total'], as_fractions['weighted_total'])

    def test_render_states_unmeasured_and_veto_without_hiding_them(self):
        text = render(evaluate(example(d1_ratio=None, d2_delta_pp=None)))
        self.assertIn('证据不足', text)
        self.assertIn('D1\tpass^k 保持率\t未采集', text)


class MechanicalProfile(TestCase):
    REGION = ('User: must keep the /api/health endpoint and never drop a.py fields.\n'
              'Traceback: FileNotFoundError in src/planner.js at line 42\n'
              'Constraint: must use Bearer TOKEN on every /api/ call.\n'
              'def run(planner):\n'
              'import http.server\n')

    def test_verbatim_availability_is_reported_per_category(self):
        presented = ('## Working state\n- keep /api/health; src/planner.js edited\n'
                     '## Errors\nTraceback: FileNotFoundError in src/planner.js at line 42')
        value = fidelity_profile(self.REGION, presented)
        self.assertGreater(value['categories']['paths']['expected'], 0)
        self.assertLess(value['rate'], 1.0)
        self.assertEqual(value['categories']['errors']['retained'], 1)
        self.assertEqual(value['categories']['code']['retained'], 0)
        self.assertEqual(value['kind'], 'verbatim_availability_not_semantic_recall')

    def test_reversibility_names_the_restore_path(self):
        self.assertEqual(reversibility([{'type': 'compaction', 'encrypted_content': 'x'}])['byte_restore'],
                         'not_exposed')
        value = reversibility([{'type': 'message'}], {'s0': {'file_path': 'a'}, 's1': {'file_path': 'b'}},
                              {'s0': True, 's1': True})
        self.assertEqual(value['byte_restore'], 'archive_read_by_source')
        self.assertEqual(value['opaque_items'], 0)
        partial = reversibility([], {'s0': {}, 's1': {}}, {'s0': True})
        self.assertEqual(partial['byte_restore'], 'partial')

    def test_repeat_variance_counts_distinct_bytes(self):
        self.assertEqual(repeat_variance(lambda: {'text': 'same'}, n=3)['distinct_digests'], 1)
        values = iter(['a', 'b', 'a'])
        self.assertEqual(repeat_variance(lambda: {'text': next(values)}, n=3)['distinct_digests'], 2)


if __name__ == '__main__':
    main()