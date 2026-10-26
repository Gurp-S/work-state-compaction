"""Freeze A3 source and a separate installed-dependency base, without production writes."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import manifest, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1')
GUI = ROOT.parent / 'gui'
AREA.mkdir()
work = AREA / 'frozen-workspace'
work.mkdir()
source = {}


def copy(source_path, relative):
    if source_path.is_dir():
        shutil.copytree(source_path, work / relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    else:
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, work / relative)


for name in ('src', 'public', 'assets', 'index.html', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts'):
    path = GUI / name
    if not path.exists():
        continue
    if path.is_dir():
        for key, value in manifest(path).items():
            source['gui/' + name + '/' + key] = value
    else:
        source['gui/' + name] = file_hash(path)
    copy(path, Path('gui') / name)
benchmark = ROOT / 'benchmarks/a3-ui-long-v1'
copy(benchmark, Path('task-contract/a3-ui-long-v1'))
for key, value in manifest(benchmark).items():
    source['task-contract/a3-ui-long-v1/' + key] = value
for name in ('BC-UI-REVIEW-RUBRIC.md', 'BC-REPLICATION-POLICY.md'):
    copy(ROOT / 'experiments' / name, Path('task-contract') / name)
    source['task-contract/' + name] = file_hash(ROOT / 'experiments' / name)
assert manifest(work) == source
print(json.dumps(dict(phase='source_frozen', files=len(source))), flush=True)


def stream_hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


deps = GUI / 'node_modules'
excluded = {'.vite', '.vite-temp', '.cache', '.tmp'}
dependency_hashes = {}
dependency_sizes = {}
for directory, folders, names in os.walk(deps, followlinks=False):
    parent = Path(directory)
    if parent == deps:
        folders[:] = [name for name in folders if name not in excluded]
    for name in folders + names:
        path = parent / name
        if path.is_symlink() or not path.resolve().is_relative_to(deps.resolve()):
            raise ValueError('dependency_link_or_escape:' + str(path))
    for name in names:
        path = parent / name
        key = path.relative_to(deps).as_posix()
        dependency_hashes[key] = stream_hash(path)
        dependency_sizes[key] = path.stat().st_size
save(AREA / 'dependency-source-manifest.json', dict(files=dependency_hashes, sizes=dependency_sizes,
    excluded_root_cache_directories=sorted(excluded), original_root=str(deps)))
print(json.dumps(dict(phase='dependency_manifest_bound', files=len(dependency_hashes), bytes=sum(dependency_sizes.values()))), flush=True)
target = AREA / 'dependency-base/node_modules'
target.mkdir(parents=True)
for index, (key, value) in enumerate(dependency_hashes.items(), 1):
    path = target / key
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(deps / key, path)
    assert stream_hash(path) == value and stream_hash(deps / key) == value, 'dependency_changed_during_freeze'
    if index % 10000 == 0:
        print(json.dumps(dict(phase='dependencies_copied', files=index)), flush=True)
assert manifest(work) == source
# Source is rechecked after the dependency copy, binding both to this freeze.
assert manifest(GUI / 'src') == {k.removeprefix('gui/src/'): v for k, v in source.items() if k.startswith('gui/src/')}
binding = dict(kind='frozen_a3_input_v1', workspace=str(work), source_manifest=source,
    dependency_base=str(target), dependency_manifest=str(AREA / 'dependency-source-manifest.json'),
    dependency_manifest_sha256=file_hash(AREA / 'dependency-source-manifest.json'),
    dependency_files=len(dependency_hashes), dependency_bytes=sum(dependency_sizes.values()),
    workspace_dependency_policy='Each A3 arm receives a physical private copy; no junction or hardlink to writable shared dependencies',
    cache_policy='Acceptance host cache is per output; runtime .vite/.cache/.tmp bases excluded',
    launch_qualified=False, production_source_unchanged=True, model_calls=0)
save(AREA / 'input-binding.json', binding)
print(json.dumps(dict(phase='frozen', source_files=len(source), dependency_files=len(dependency_hashes),
                     dependency_bytes=sum(dependency_sizes.values()), model_calls=0)), flush=True)
