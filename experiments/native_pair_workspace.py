"""Snapshot an arm and restore file bytes without moving a live native cwd."""
from pathlib import Path
import shutil

from native_evidence import digest, manifest, save


def _inside(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("unsafe_workspace_relative_path")
    path.resolve().relative_to(root)
    return path


def preserve_arm(area, arm, frozen, initial, *, restore_initial, rehearsal=False, workspace=None):
    area, frozen = Path(area).resolve(), Path(frozen).resolve()
    if arm not in {"B", "C"}:
        raise ValueError("unregistered_arm")
    if workspace is None:
        work = area / "workspace"
        if work.is_symlink() or work.resolve().parent != area:
            raise ValueError("unsafe_workspace_root")
    else:
        from native_study_workspace import validate
        work, _ = validate(area, workspace, frozen, initial)
    destination = area / arm / ("rehearsal-workspace" if rehearsal else "final-workspace")
    prefix = "rehearsal-" if rehearsal else ""
    if destination.parent.resolve().parent != area or destination.exists():
        raise ValueError("unsafe_or_existing_archive")
    if frozen == work or frozen.is_relative_to(work):
        raise ValueError("frozen_source_inside_workspace")
    # Resolve every candidate before mutation; no directory removal is needed.
    for relative in initial:
        _inside(work, relative)
        _inside(frozen, relative)
    if manifest(frozen) != initial:
        raise ValueError("frozen_workspace_changed")
    if any(path.is_symlink() or path.resolve().is_relative_to(work) is False
           for path in work.rglob("*")):
        raise ValueError("workspace_link_outside_snapshot_contract")
    before = manifest(work)
    for relative in before:
        _inside(work, relative)
    shutil.copytree(work, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if manifest(destination) != before or manifest(work) != before:
        raise ValueError("workspace_changed_during_snapshot")
    saved = {"archive": str(destination), "archive_manifest_sha256": digest(before),
             "archive_verified": True, "cwd_directory_moved": False}
    save(area / arm / (prefix + "snapshot-audit.json"), saved)
    removed_caches = []
    if restore_initial:
        for relative, expected in initial.items():
            if before.get(relative) != expected:
                target = _inside(work, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(_inside(frozen, relative), target)
        for relative in sorted(set(before) - set(initial)):
            _inside(work, relative).unlink()
        # The source manifest deliberately excludes bytecode. A retained cwd
        # must not carry an earlier arm's compiled modules into the next arm.
        caches = [path for path in work.rglob("*") if path.is_file()
                  and ("__pycache__" in path.relative_to(work).parts or path.suffix == ".pyc")]
        for path in caches:
            relative = path.relative_to(work).as_posix()
            _inside(work, relative).unlink()
            removed_caches.append(relative)
        if manifest(work) != initial:
            raise ValueError("workspace_restore_mismatch")
    saved["restored_initial"] = restore_initial
    saved["removed_runtime_caches"] = sorted(removed_caches)
    saved["workspace_manifest_sha256"] = digest(manifest(work))
    save(area / arm / (prefix + "workspace-lifecycle.json"), saved)
    return saved
