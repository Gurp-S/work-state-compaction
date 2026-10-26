"""Freeze explicitly allowlisted four-app inputs, excluding author solutions.

This defines package contents, not an OS read sandbox. External author files
are not copied; absence of model access outside the package needs separate proof.
"""
from pathlib import Path
import shutil

from native_evidence import digest, file_hash, manifest, read, save

TASKS = ('collaboration', 'files', 'imports', 'booking')


def _files(folder):
    root = folder.resolve()
    for path in sorted(root.rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('application_input_link_or_escape')
        if path.is_file():
            yield path


def freeze_task(suite, task_id, destination):
    suite = Path(suite).resolve()
    destination = Path(destination).resolve()
    if task_id not in TASKS:
        raise ValueError('application_task_not_registered')
    if destination.is_relative_to(suite) or suite.is_relative_to(destination):
        raise ValueError('application_freeze_source_destination_overlap')
    task = suite / 'tasks' / task_id
    spec = read(task / 'task.json')
    if [s['id'] for s in spec['stages']] != [f'S{i}' for i in range(1, 9)]:
        raise ValueError('application_stage_registration_invalid')
    inputs = {}
    for path in _files(task / 'starter'):
        inputs[path.relative_to(task / 'starter').as_posix()] = path
    for name in ('TASK.md', 'task.json'):
        inputs[f'task-contract/tasks/{task_id}/{name}'] = task / name
    inputs['task-contract/COMMON.md'] = suite / 'COMMON.md'
    for path in _files(suite / 'acceptance'):
        inputs['task-contract/acceptance/' + path.relative_to(suite / 'acceptance').as_posix()] = path
    hashes = {name: file_hash(path) for name, path in inputs.items()}
    destination.mkdir(parents=True, exist_ok=False)
    frozen = destination / 'frozen-workspace'
    frozen.mkdir()
    for name, path in inputs.items():
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    if manifest(frozen) != hashes or any(file_hash(path) != hashes[name] for name, path in inputs.items()):
        raise ValueError('application_input_changed_during_freeze')
    record = dict(kind='frozen_application_input_v1', task_id=task_id, workspace=str(frozen),
        source_manifest=hashes, source_manifest_sha256=digest(hashes), stages=spec['stages'],
        contract_sha256=digest({k: h for k, h in hashes.items() if k.startswith('task-contract/')}),
        task_request_paths=[f'task-contract/tasks/{task_id}/TASK.md', 'task-contract/COMMON.md'],
        acceptance_entrypoint='task-contract/acceptance/run.py',
        excluded_material='Author calibration implementations, validation receipts, versions, caches and other tasks',
        read_isolation_proven=False, launch_qualified=False)
    save(destination / 'input-binding.json', record)
    return record
