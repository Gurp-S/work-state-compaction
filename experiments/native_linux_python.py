"""Opt-in readonly Python mount; the original native/network policy is retained."""
from pathlib import PurePosixPath
from native_linux_envelope import command as base_command, checked_absolute

POLICY = 'linux_closed_mounts_python_v1'
DIRECTORY = 'python-3.11.18-20261026-linux-musl'


def command(runtime, actor_root, python_root):
    python_root = checked_absolute(python_root)
    if PurePosixPath(python_root).name != DIRECTORY:
        raise ValueError('linux_python_mount_unregistered')
    paths = [PurePosixPath(checked_absolute(p)) for p in (runtime, actor_root, python_root)]
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
           for i,a in enumerate(paths) for b in paths[i+1:]):
        raise ValueError('linux_python_mount_overlap')
    result = base_command(runtime, actor_root)
    result[-1:-1] = ['--ro-bind', python_root, '/opt/python',
        '--setenv', 'PATH', '/opt/python/bin:/opt/codex/codex-path:/usr/bin:/bin',
        '--setenv', 'PYTHONDONTWRITEBYTECODE', '1']
    return result
