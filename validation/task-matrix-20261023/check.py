"""Scoped matrix and existing scheduler compatibility checks, no model calls."""
import io
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
sys.path.insert(0,str(ROOT/'tests'))
from native_evidence import file_hash,save

destination=Path(__file__).parent/'checks.json'
if destination.exists(): raise FileExistsError(destination)
source={p.relative_to(ROOT).as_posix():file_hash(p) for folder in ('src','experiments','tests')
        for p in sorted((ROOT/folder).rglob('*.py'))}
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_native_task_matrix','test_native_repeated_pairs'])
stream=io.StringIO()
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
assert all(file_hash(ROOT/p)==h for p,h in source.items())
receipt=dict(tests=result.testsRun,passed=result.wasSuccessful(),source_manifest=source,
    failures=[dict(test=t.id(),trace=s) for t,s in result.failures],
    errors=[dict(test=t.id(),trace=s) for t,s in result.errors],log=stream.getvalue(),new_model_calls=0,
    scope='5 tasks x 3 pairs offline scheduling and settlement; not native task quality')
save(destination,receipt)
print(stream.getvalue())
sys.exit(0 if result.wasSuccessful() else 1)
