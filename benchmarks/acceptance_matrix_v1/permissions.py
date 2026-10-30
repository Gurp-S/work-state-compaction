"""Per-process native profile; no global Codex configuration changes."""
import json
from pathlib import Path

PROFILE = 'wsc_matrix_actor'


def runtime_startup_flags(plan):
    flags=plan.get('runtime_startup_flags',[])
    if flags not in ([],['mcp_servers.node_repl.enabled=false']):
        raise ValueError('matrix_runtime_startup_flags_unregistered')
    return list(flags)


def permission_flags(workspace, blocked_roots):
    work = Path(workspace).resolve(strict=True)
    if not work.is_dir():
        raise ValueError('matrix_workspace_not_directory')
    blocked = sorted({str(Path(p).resolve(strict=True)) for p in blocked_roots})
    if not blocked or str(work).casefold() in {p.casefold() for p in blocked}:
        raise ValueError('matrix_permission_boundary_invalid')
    # CLI dotted-key parsing does not unquote absolute Windows path keys.
    values = [(p, 'deny') for p in blocked]+[(str(work), 'write')]
    table = '{'+','.join(json.dumps(p)+'='+json.dumps(access) for p, access in values)+'}'
    return ['permissions.'+PROFILE+'.extends=":read-only"',
            'permissions.'+PROFILE+'.network.enabled=false',
            'permissions.'+PROFILE+'.filesystem='+table]
