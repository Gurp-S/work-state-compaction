"""Run the quarantined mechanism tests without pytest (CI entry point).

Every module under tests/ is loaded unless it is listed in BLOCKED with the
removed wiring that makes it unrunnable. Pass --all to attempt blocked modules
too, for a maintainer who has restored the wiring.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / 'tests'
sys.path[:0] = [str(ROOT.parent / 'src'), str(ROOT), str(TESTS),
                str(ROOT.parent / 'experiments'), str(ROOT.parent / 'tests')]

BLOCKED = {
    'test_blob_gc_restore': 'durable_ops.recover no longer collects blobs',
    'test_command_containment': 'bounded command generator wiring removed from generation/cli',
    'test_control_retention': 'prepare(include_selection_facts) removed',
    'test_native_generation_binding': 'experiments/ fixture imports removed wsc APIs',
    'test_native_hot_checkpoint': 'experiments/ fixture imports removed wsc APIs',
    'test_native_incremental_candidate': 'experiments/ fixture imports removed wsc APIs',
    'test_native_indexed_checkpoint': 'experiments/ fixture imports removed wsc APIs',
    'test_native_scope_observation': 'scope/coverage selection wiring removed',
    'test_native_selection_wire': 'experiments/ fixture imports removed wsc APIs',
    'test_observation_coverage': 'coverage selection wiring removed',
    'test_projected_selection_facts': 'prepare(include_selection_facts)/admit_generation removed',
    'test_publication_memory': 'WSC(publication_policy=...) removed',
    'test_quote_selection': 'selection-fact export wiring removed',
    'test_scoped_queries': 'WSC(query_policy=...) removed',
    'test_selection_facts': 'prepare(include_selection_facts) removed',
    'test_span_boundaries': 'selection-fact publication wiring removed',
    'test_span_reference_schema': 'experiments/ probe imports removed wsc.quote_selection',
    'test_span_selection': 'prepare(include_selection_facts) removed',
    'test_verification_checkpoint': 'verification adapter wiring removed from publication',
}


def modules(blocked):
    return sorted(path.stem for path in TESTS.glob('test_*.py')
                  if path.stem not in blocked)


def main(argv):
    all_modules = '--all' in argv
    blocked = set() if all_modules else set(BLOCKED)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in modules(blocked))
    if not all_modules:
        for name, reason in BLOCKED.items():
            print(f'blocked {name}: {reason}')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
