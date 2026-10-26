"""One independent source-stable supplemental grade, zero model calls."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, manifest
from native_owned_process import ProcessOwner
AREA = Path(sys.argv[1]) if len(sys.argv)>1 else Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
reg = read(AREA / 'prepared.json')['registration']
work = Path(reg['workspace'])
assert read(AREA / 'result.json')['cleanup']['empty_confirmed']
before = manifest(work / 'gui/src')
assert before == read(AREA / 'S3-acceptance/registration.json')['source_manifest']
scripts = Path(__file__).parent
jobs = [('concurrency', scripts / 's3-concurrency-direct.mjs', [str(work/'gui'), str(AREA/'S3-concurrency'), reg['fixture_root']]),
    ('scope', scripts / 's3-scope-check.mjs', [str(work/'gui'), reg['fixture_root'], str(AREA/'S3-scope')]),
    ('clipping', scripts / 'check_s2_clipping.mjs', [str(work/'gui'), reg['fixture_root'], str(AREA/'S3-clipping')])]
save(AREA / 'supplemental-grade-registration.json', dict(source_manifest=before,
    scripts_sha256={name: file_hash(path) for name, path, _ in jobs},
    scope='Independent S3 concurrency, scope/date/keyboard, production host real-wheel checks', model_calls=0))
def run(job):
    name, script, args = job
    owner = ProcessOwner()
    folder = AREA / ('S3-' + name + '-driver')
    folder.mkdir(exist_ok=False)
    result = dict(name=name)
    proc = None
    try:
        with (folder / 'stdout.txt').open('x', encoding='utf-8') as stdout, (folder / 'stderr.txt').open('x', encoding='utf-8') as stderr:
            env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': reg['browser_cache']}
            proc = subprocess.Popen([reg['node_executable'], str(script), *args], cwd=work,
                env=env, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            owner.attach(proc)
            result['exit_code'] = proc.wait(timeout=120)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ':' + str(exc)
    finally:
        result['cleanup'] = owner.close()
        if proc:
            proc.wait(timeout=5)
    save(folder / 'result.json', result)
    return result
with ThreadPoolExecutor(max_workers=3) as pool:
    outcomes = list(pool.map(run, jobs))
after = manifest(work/'gui/src')
save(AREA / 'supplemental-grade.json', dict(drivers=outcomes, source_unchanged=before == after, model_calls=0,
    concurrency=read(AREA/'S3-concurrency/result.json'), scope=read(AREA/'S3-scope/result.json'),
    clipping=read(AREA/'S3-clipping/result.json')))
print(dict(source_unchanged=before == after, drivers=outcomes,
    concurrency=read(AREA/'S3-concurrency/result.json')['passed'], scope=read(AREA/'S3-scope/result.json')['passed'],
    clipping=read(AREA/'S3-clipping/result.json')['clipping_observed']))
