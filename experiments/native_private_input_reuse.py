"""Reuse a private, unexecuted input copy after a recorded bootstrap failure."""
import os
from pathlib import Path

from native_evidence import read, file_hash


def verify(spec, job, binding):
    work = Path(job['resources']['workspace']).resolve()
    if work != Path(spec['workspace']).resolve():
        raise ValueError('application_reuse_workspace_mismatch')
    for name in ('prepared', 'result'):
        if file_hash(spec[name]) != spec[name + '_sha256']:
            raise ValueError('application_reuse_receipt_changed')
    prepared, result = read(spec['prepared']), read(spec['result'])
    if (Path(prepared['registration']['workspace']).resolve() != work
            or prepared['binding_sha256'] != spec['binding_sha256']
            or result['state'] != 'infrastructure_error' or result['phases']
            or result.get('admission_matched') is not False
            or not result.get('cleanup')
            or not all(item['empty_confirmed'] for item in result['cleanup'])):
        raise ValueError('application_reuse_not_unexecuted_closed_input')
    actual = {}
    for directory, folders, names in os.walk(work, followlinks=False):
        parent = Path(directory)
        for name in folders:
            path = parent / name
            if path.is_symlink() or getattr(path.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400:
                raise ValueError('application_reuse_directory_link')
        folders[:] = [name for name in folders if (parent / name).relative_to(work).as_posix() != 'gui/node_modules'
                      and name != '__pycache__']
        for name in names:
            path = parent / name
            if path.is_symlink():
                raise ValueError('application_reuse_source_link')
            if path.suffix != '.pyc':
                actual[path.relative_to(work).as_posix()] = file_hash(path)
    if actual != binding['source_manifest']:
        raise ValueError('application_reuse_source_changed')
    return dict(previous_prepared=spec['prepared'], previous_result=spec['result'],
                source_reverified=True, dependency_reverification='performed_by_materializer')
