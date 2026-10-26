"""Record one bounded offline check against its exact source bytes."""
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'tests'))
from native_evidence import file_hash, save

destination = Path(__file__).parent / sys.argv[1]
if destination.exists():
    raise FileExistsError(destination)
paths = [ROOT/'experiments/native_repeated_pairs.py', ROOT/'tests/test_native_repeated_pairs.py',
         ROOT/'experiments/native_continuity_checks.py', ROOT/'experiments/native_evidence.py']
before = {str(p.relative_to(ROOT)): file_hash(p) for p in paths}
suite = unittest.defaultTestLoader.loadTestsFromName('test_native_repeated_pairs')
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
assert before == {str(p.relative_to(ROOT)): file_hash(p) for p in paths}
receipt = dict(tests=result.testsRun, failures=[dict(test=t.id(), trace=s) for t,s in result.failures],
               errors=[dict(test=t.id(), trace=s) for t,s in result.errors], log=stream.getvalue(),
               passed=result.wasSuccessful(), source_manifest=before, new_model_calls=0,
               scope='Offline worker scheduling and settlement, not live native process integration')
save(destination, receipt)
print(stream.getvalue())
sys.exit(0 if result.wasSuccessful() else 1)
