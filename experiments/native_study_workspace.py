"""One owned stable workspace across acquisition, qualification and comparison."""
from pathlib import Path
import shutil

from native_evidence import digest, manifest, read, save

RECEIPT = "workspace-ownership.json"
AREAS = {"acquisition", "qualification", "comparison"}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def create(owner, frozen):
    owner, frozen = Path(owner).resolve(), Path(frozen).resolve()
    require(not owner.exists(), "study_owner_already_exists")
    require(frozen.is_dir(), "frozen_workspace_missing")
    require(not frozen.is_relative_to(owner), "frozen_source_inside_study")
    initial = manifest(frozen)
    require(bool(initial), "empty_study_source")
    owner.mkdir(parents=True, exist_ok=False)
    work = owner / "workspace"
    shutil.copytree(frozen, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    require(manifest(work) == initial, "study_copy_mismatch")
    receipt = {"format": "wsc.native-study-workspace/1", "owner": str(owner),
               "workspace": str(work), "frozen": str(frozen), "initial_manifest_sha256": digest(initial),
               "metadata_areas": sorted(AREAS), "directory_migration": False}
    save(owner / RECEIPT, receipt)
    return receipt


def validate(area, workspace, frozen, initial, *, require_initial=False):
    area, workspace, frozen = Path(area).resolve(), Path(workspace), Path(frozen).resolve()
    owner = workspace.parent.resolve()
    receipt_path = owner / RECEIPT
    require(not workspace.is_symlink() and workspace.resolve() == owner / "workspace",
            "unsafe_study_workspace_root")
    require(area.parent == owner and area.name in AREAS, "unregistered_study_area")
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "study_ownership_missing")
    value = read(receipt_path)
    expected = {"format": "wsc.native-study-workspace/1", "owner": str(owner),
                "workspace": str(workspace.resolve()), "frozen": str(frozen),
                "initial_manifest_sha256": digest(initial), "metadata_areas": sorted(AREAS),
                "directory_migration": False}
    require(value == expected, "study_ownership_mismatch")
    require(workspace.is_dir(), "study_workspace_missing")
    if require_initial:
        require(manifest(workspace) == initial, "study_workspace_not_at_start")
    return workspace.resolve(), receipt_path
