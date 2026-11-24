"""The authored eval set must stay valid, discriminative and honest.

Validity: every case really compresses under every arm's budget, the product
arm's evidence verifies, and repeated builds are byte-identical.

Discrimination: the arms must score differently, and the ablations must move in
the expected direction (dropping distillation loses round-1 state; dropping
expiry leaks the stale claim). A set that stops separating algorithms is a
regression, not a passing test.
"""
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]
from coding_compaction_v1 import cases as case_module
from coding_compaction_v1 import run as runner


class FixtureValidity(TestCase):
    def test_every_case_compresses_under_every_arm_and_discriminates(self):
        with tempfile.TemporaryDirectory() as directory:
            for factory in case_module.CASES:
                case = factory()
                result = runner.measure_case(case, Path(directory))
                self.assertTrue(result['gate']['valid'], (case['case'], result['gate']))
                self.assertTrue(result['discriminative'], (case['case'], result['spread']))
                self.assertLess(result['gate']['ratio'], 0.85)
                self.assertEqual(result['variance']['distinct_digests'], 1)

    def test_every_probe_and_exclusion_names_a_catalog_fact(self):
        for factory in case_module.CASES:
            case = factory()
            catalog = runner.fact_catalog(case)
            for round_number in (1, 2):
                for probe in runner._round_probes(case, round_number):
                    for fact_id in probe['expects'] + probe.get('excludes', []):
                        self.assertIn(fact_id, catalog, (case['case'], fact_id))
            self.assertGreater(len(case['distill']), 0)
            self.assertGreater(len(case['round2']['distill']), 0)


class ArmSeparation(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.case = case_module.lease_identity_case()
        cls.result = runner.measure_case(cls.case, Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_product_arm_keeps_state_and_baselines_lose_it(self):
        arms = self.result['arms']
        # Evidence text now lives in the cold store; the product arm keeps the
        # ledger state and the index, so one evidence probe may miss by design.
        self.assertGreaterEqual(arms['wsc']['probes'][2]['score'], 0.8)
        self.assertLess(arms['truncation']['probes'][2]['score'], 1.0)
        self.assertLess(arms['extractive']['probes'][2]['score'], 1.0)
        self.assertGreater(arms['wsc']['catalog'][2]['key_recall'],
                           arms['truncation']['catalog'][2]['key_recall'])
        self.assertEqual(arms['wsc']['probes'][2]['stale_present'], [])
        self.assertFalse(arms['truncation']['budget_ok'][1] is False)

    def test_ablations_move_in_the_expected_direction(self):
        arms = self.result['arms']
        # Without distillation the round-1 ledger facts are never presented.
        self.assertLess(arms['wsc_evidence_only']['probes'][1]['score'],
                        arms['wsc']['probes'][1]['score'])
        # Without expiry the superseded verification leaks into round 2.
        self.assertEqual(arms['wsc_sticky']['probes'][2]['stale_present'], ['v1'])
        self.assertLess(arms['wsc_sticky']['probes'][2]['score'],
                        arms['wsc']['probes'][2]['score'])

    def test_only_the_product_family_can_restore_bytes(self):
        arms = self.result['arms']
        self.assertEqual(arms['wsc']['reversibility']['byte_restore'], 'archive_read_by_source')
        self.assertNotIn('reversibility', arms['truncation'])
        self.assertNotIn('reversibility', arms['extractive'])

    def test_product_dominates_the_baselines_at_no_more_bytes(self):
        rows = {(row['better'], row['worse']): row
                for row in self.result['comparison']['dominance']}
        for baseline in ('truncation', 'extractive'):
            row = rows[('wsc', baseline)]
            self.assertTrue(row['dominates'], row)
            self.assertLessEqual(self.result['arms']['wsc']['ratio'][1],
                                 self.result['arms'][baseline]['ratio'][1] + 0.02)


class ProbeScoring(TestCase):
    def test_expectations_and_exclusions_are_scored_mechanically(self):
        catalog = {'a': 'alpha fact', 'b': 'beta stale claim'}
        probes = [{'question': 'q', 'expects': ['a'], 'excludes': ['b']}]
        self.assertEqual(runner.probe_report(probes, catalog, 'alpha fact only')['score'], 1.0)
        leaked = runner.probe_report(probes, catalog, 'alpha fact and beta stale claim')
        self.assertEqual(leaked['score'], 0.5)
        self.assertEqual(leaked['stale_present'], ['b'])
        self.assertEqual(runner.probe_report(probes, catalog, 'nothing')['score'], 0.5)

    def test_dominance_requires_quality_and_no_more_bytes(self):
        def arm(ratio, probe, constraint=1.0, recall=1.0):
            return {'ratio': {1: ratio},
                    'probes': {2: {'score': probe, 'stale_present': []}},
                    'oracle': {2: {'constraint_retention': constraint}},
                    'catalog': {2: {'key_recall': recall}}}
        report = {'good': arm(0.2, 1.0), 'worse': arm(0.4, 0.5), 'fat': arm(0.5, 1.0)}
        rows = {(row['better'], row['worse']): row
                for row in runner.compare('c', report)['dominance']}
        self.assertTrue(rows[('good', 'worse')]['dominates'])
        self.assertTrue(rows[('good', 'fat')]['dominates'], 'equal quality at fewer bytes')
        self.assertFalse(rows[('fat', 'good')]['dominates'], 'more bytes is not dominance')


if __name__ == '__main__':
    main()