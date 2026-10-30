"""Opt-in outer filesystem boundary using the unchanged bundled bubblewrap.

This describes offline mounts, not provider connectivity or a paid actor gate.
"""
from pathlib import PurePosixPath

POLICY='linux_closed_mounts_v1'


def checked_absolute(value):
    path=PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path)=='/':
        raise ValueError('linux_envelope_path_invalid')
    return str(path)


def command(runtime, actor_root):
    runtime=checked_absolute(runtime);actor_root=checked_absolute(actor_root)
    if PurePosixPath(runtime).name!='codex-0.165.0-alpha.1.2-linux-x64' or PurePosixPath(actor_root).name!='actor-root':
        raise ValueError('linux_envelope_mount_not_registered')
    if runtime==actor_root or PurePosixPath(runtime).is_relative_to(actor_root) or PurePosixPath(actor_root).is_relative_to(runtime):
        raise ValueError('linux_envelope_mount_overlap')
    return [runtime+'/codex-resources/bwrap','--unshare-all','--die-with-parent','--new-session',
      '--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib',
      '--ro-bind',runtime,'/opt/codex','--bind',actor_root,'/work',
      '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--chdir','/work/actor',
      '--clearenv','--setenv','PATH','/opt/codex/codex-path:/usr/bin:/bin',
      '--setenv','HOME','/work/home','--setenv','CODEX_HOME','/work/home/.codex',
      '--uid','65534','--gid','65534','--cap-drop','ALL','--']
