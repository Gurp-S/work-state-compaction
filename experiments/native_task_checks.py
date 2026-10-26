"""Pinned, explicitly named checks on private copies of a native task workspace."""
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys

from native_evidence import digest, file_hash, manifest, save


def require(value, reason):
    if not value:
        raise ValueError(reason)


def grade(workspace, grader, names, destination):
    require(isinstance(names, list) and names and len(names) == len(set(names)) and
            all(isinstance(n, str) and len(n.split('.')) == 2 and
                all(p.isidentifier() for p in n.split('.')) and n.split('.')[1].startswith('test_')
                for n in names), "task_check_names_invalid")
    workspace, destination = Path(workspace), Path(destination)
    before = manifest(workspace)
    destination.mkdir(parents=True)
    fixture = destination / "fixture"
    shutil.copytree(workspace / "src", fixture / "src", ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    require(manifest(fixture / "src") == manifest(workspace / "src"), "task_check_copy_changed")
    (fixture / "tests").mkdir()
    shutil.copy2(grader, fixture / "tests/_task_grader.py")
    probe = '''import io,json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path('tests').resolve()))
import _task_grader as module
suite=unittest.defaultTestLoader.loadTestsFromNames(json.loads(sys.argv[1]),module)
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
import wsc
print(json.dumps(dict(tests=result.testsRun,failures=[dict(test=t.id(),trace=s) for t,s in result.failures],errors=[dict(test=t.id(),trace=s) for t,s in result.errors],skipped=len(result.skipped),imported_from=wsc.__file__,log=stream.getvalue())))
'''
    process = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', probe, json.dumps(names)],
                             cwd=fixture, capture_output=True, text=True, encoding='utf-8', timeout=30)
    (destination / 'stdout.txt').write_text(process.stdout, encoding='utf-8')
    (destination / 'stderr.txt').write_text(process.stderr, encoding='utf-8')
    require(process.returncode == 0, "task_grader_process_failed")
    result = json.loads(process.stdout)
    require(Path(result['imported_from']).resolve().is_relative_to((fixture / 'src').resolve()),
            "task_grader_import_wrong_source")
    require(manifest(workspace) == before, "task_check_changed_workspace")
    result.update(source_manifest=before, source_manifest_sha256=digest(before), names=names,
                  observed_at=datetime.now(timezone.utc).isoformat(),
                  grader_sha256=file_hash(grader), scope='named_task_methods',
                  passed=not (result['failures'] or result['errors'] or result['skipped'])
                         and result['tests'] == len(names))
    save(destination / 'receipt.json', result)
    return result
