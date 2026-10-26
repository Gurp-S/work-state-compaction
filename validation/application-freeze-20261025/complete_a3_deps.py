"""Complete verified copy after concurrent path-resolution guard failure.

Validate immutable manifest paths and reparse-free roots/directories before
parallel writes; every copied/reused byte remains checked against the seal.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import file_hash, manifest, read, save

AREA = Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1').resolve()
GUI = ROOT.parent / 'gui'
bound = read(AREA / 'dependency-source-manifest.json')
source = Path(bound['original_root']).resolve()
target = (AREA / 'dependency-base/node_modules').resolve()
work = AREA / 'frozen-workspace'
assert not (AREA / 'input-binding.json').exists()
assert target.is_relative_to(AREA)
for key in bound['files']:
    name = PurePosixPath(key)
    assert not name.is_absolute() and '..' not in name.parts and ':' not in key and '\\' not in key
for directory_root in (source, target):
    for parent, directories, names in os.walk(directory_root, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            assert not (path.lstat().st_file_attributes & 0x400), 'reparse_directory_in_dependency_root'
save(AREA / 'copy-completion-registration.json', dict(
    earlier_copy_error='Concurrent resume failed a source/destination containment assertion. Post-stop scan found no escaping path; exact transient offending path was not logged.',
    change='Prevalidate sealed relative paths and reparse-free directory trees; resolve roots once; hash every source/target file',
    source_manifest_sha256=file_hash(AREA / 'dependency-source-manifest.json'), parallel_workers=8, model_calls=0))


def hashed(path):
    h = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def copy(item):
    key, expected = item
    src, dst = source / key, target / key
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
save(AREA / 'input-binding.json', dict(kind='frozen_a3_input_v1', workspace=str(work), source_manifest=frozen,
    dependency_base=str(target), dependency_manifest=str(AREA / 'dependency-source-manifest.json'),
    dependency_manifest_sha256=file_hash(AREA / 'dependency-source-manifest.json'), dependency_files=len(bound['files']),
    dependency_bytes=sum(bound['sizes'].values()), copy_counts=counts,
    workspace_dependency_policy='Physical private dependency copies per arm; no shared writable junction or hardlink',
    cache_policy='Per-output acceptance cache; dependency-root caches excluded',
    launch_qualified=False, production_source_unchanged=True, model_calls=0))
print(json.dumps(dict(status='frozen', source_files=len(frozen), dependency_files=len(bound['files']), **counts, model_calls=0)), flush=True)
