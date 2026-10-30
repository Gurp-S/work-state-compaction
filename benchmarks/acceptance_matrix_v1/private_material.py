"""Explicit, sealed experiment material inventory; not a general sandbox proof."""
from pathlib import Path
from .workspace_runtime import digest


POLICY = 'sealed_private_material_v1'


def within(path, root):
    return path == root or path.is_relative_to(root)


def regular(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('private_material_link_not_allowed')
    if not path.is_file():
        raise ValueError('private_material_not_file')
    return path.resolve(strict=True)


def inventory(files, denied_roots, *, workspace):
    """Caller declares artifacts and isolation domains; no content classification."""
    work = Path(workspace).resolve(strict=True)
    if not work.is_dir():
        raise ValueError('private_material_workspace_not_directory')
    roots = sorted({Path(p).resolve(strict=True) for p in denied_roots}, key=str)
    if not roots:
        raise ValueError('private_material_roots_missing')
    if any(within(work, p) or within(p, work) for p in roots):
        raise ValueError('private_material_workspace_overlap')
    # Keep only minimal enclosing domains; avoid costly duplicate ACL setup.
    roots = [p for p in roots if not any(p != q and within(p, q) for q in roots)]
    entries = {}
    for source in files:
        path = regular(source)
        if not any(within(path, p) for p in roots):
            raise ValueError('private_material_uncovered:' + str(path))
        entries[str(path)] = digest(path)
    if not entries:
        raise ValueError('private_material_files_missing')
    return dict(policy=POLICY, workspace=str(work), blocked=[str(p) for p in roots],
                files=dict(sorted(entries.items())), scope='Declared files and native command/exec only')


def verify(value, *, workspace):
    if value.get('policy') != POLICY:
        raise ValueError('private_material_policy_unknown')
    actual = inventory(value['files'], value['blocked'], workspace=workspace)
    if actual != value:
        raise ValueError('private_material_inventory_changed')
    return actual
