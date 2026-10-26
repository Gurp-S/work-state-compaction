"""Resume the intentionally stopped serial local copy with private parallel I/O."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import file_hash, manifest, read, save

AREA = Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1')
GUI = ROOT.parent / 'gui'
source = GUI / 'node_modules'
target = AREA / 'dependency-base/node_modules'
work = AREA / 'frozen-workspace'
assert not (AREA / 'input-binding.json').exists()
assert target.resolve().is_relative_to(AREA.resolve())
bound = read(AREA / 'dependency-source-manifest.json')
save(AREA / 'copy-resume-registration.json', dict(reason='Measured serial copy throughput; resume verified files and parallelize remaining I/O',
    serial_pid=26728, parallel_workers=8, source_manifest_sha256=file_hash(AREA / 'dependency-source-manifest.json'), model_calls=0))


def hashed(path):
    h = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def copy(item):
    key, expected = item
    src, dst = source / key, target / key
    assert src.resolve().is_relative_to(source.resolve()) and dst.resolve().is_relative_to(target.resolve())
    assert not src.is_symlink() and not dst.is_symlink()
    if dst.is_file() and hashed(dst) == expected:
        assert hashed(src) == expected
        return 'reused'
    assert hashed(src) == expected, 'installed_dependency_changed'
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    assert hashed(dst) == expected
    return 'copied'


counts = dict(reused=0, copied=0)
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = [pool.submit(copy, item) for item in bound['files'].items()]
    for index, future in enumerate(as_completed(futures), 1):
        counts[future.result()] += 1
        if index % 10000 == 0:
            print(json.dumps(dict(verified=index, **counts)), flush=True)
frozen = manifest(work)
for key, value in frozen.items():
    if key.startswith('gui/'):
        path = GUI / key.removeprefix('gui/')
    elif key.startswith('task-contract/a3-ui-long-v1/'):
        path = ROOT / 'benchmarks/a3-ui-long-v1' / key.removeprefix('task-contract/a3-ui-long-v1/')
    else:
        path = ROOT / 'experiments' / Path(key).name
    assert file_hash(path) == value
assert len(bound['files']) == len([p for p in target.rglob('*') if p.is_file()])
binding = dict(kind='frozen_a3_input_v1', workspace=str(work), source_manifest=frozen,
    dependency_base=str(target), dependency_manifest=str(AREA / 'dependency-source-manifest.json'),
    dependency_manifest_sha256=file_hash(AREA / 'dependency-source-manifest.json'),
    dependency_files=len(bound['files']), dependency_bytes=sum(bound['sizes'].values()),
    workspace_dependency_policy='Each A3 arm receives a physical private copy, no writable shared junction or hardlink',
    copy_counts=counts, cache_policy='Private acceptance output cache; installed root caches excluded',
    launch_qualified=False, production_source_unchanged=True, model_calls=0)
save(AREA / 'input-binding.json', binding)
print(json.dumps(dict(status='frozen', files=len(frozen), dependencies=len(bound['files']), **counts, model_calls=0)), flush=True)
