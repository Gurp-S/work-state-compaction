"""One read-only downstream observation of an existing imperfect handoff.

Archived items are replayed or given a registered provenance-only presentation.
This does not confirm the historical publication or grant B/C qualification.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from native_evidence import digest, file_hash, manifest, read, save
from native_pair_admission import observe
from native_execution_binding import report_execution_item
from native_thread_archive import archive_threads
from wsc.recorded_understandings import recorded_items
from run_native_pair import (MODEL, SETTINGS, NativeRPC, initialize, import_items,
                             phase, audit_import, audit_host, verify_pins, require)


REQUEST = "请根据已完成的工作给出最终交付报告，说明改动、验证结果与仍未验证的范围，并附可追溯的证据。"


def presentation_items(package, presentation):
    require(presentation in {"covered", "recorded"}, "report_presentation_unregistered")
    if presentation == "covered":
        return package["items"]
    require(package["through"] == package["binding"]["cut"], "report_projection_tail_unsupported")
    return recorded_items(package["items"], read(package["understanding_index"]),
                          working_state_index=len(package["items"]) - 1)


def preflight(reg):
    verify_pins(reg)
    require(manifest(reg["workspace"]) == reg["task_manifest"], "report_task_workspace_changed")
    package = read(reg["package"])
    require(digest({k: v for k, v in package.items() if k != "package_digest"})
            == package["package_digest"], "report_package_integrity_mismatch")
    require(digest(package["items"]) == reg["items_sha256"], "report_items_changed")
    for group in ("evidence", "excerpt_evidence"):
        for locator in package.get(group, {}).values():
            require(file_hash(locator["file_path"]) == locator["sha256"], "report_export_changed")
            if "readable_path" in locator:
                require(file_hash(locator["readable_path"]) == locator["readable_sha256"],
                        "report_readable_export_changed")
    for name in ("source_index", "understanding_index"):
        require(digest(read(package[name])) == package[name + "_sha256"], "report_index_changed")
    require(reg.get("execution_fact") == report_execution_item(reg["workspace"], reg["task_manifest"]),
            "report_execution_fact_missing_or_changed")
    items = presentation_items(package, reg.get("presentation", "covered"))
    require(digest(items) == reg.get("presented_items_sha256", reg["items_sha256"]),
            "report_presentation_changed")
    return items + [reg["execution_fact"]]


def prepare(area, source, task, executable, *, presentation="covered"):
    require(not area.exists(), "report_probe_already_registered")
    package = read(source / "package.json")
    task_reg = read(task / "registration.json")
    task_manifest = manifest(task / "workspace")
    require(task_manifest == manifest(task / "C/final-workspace"), "report_task_not_archived_final")
    # Only frozen exports are inputs, never the mutable historical SQLite DB.
    paths = [source / "package.json", source / "model-draft.json", executable]
    paths += [p for p in (source / "exports").rglob("*") if p.is_file()]
    paths += [p for folder in ("src", "experiments", "tests")
              for p in (HERE.parent / folder).rglob("*.py")]
    reg = {"purpose": "archived_handoff_downstream_diagnostic_not_C_qualification",
        "source": str(source), "package": str(source / "package.json"),
        "historical_package_binding": package["binding"],
        "workspace": str(task / "workspace"), "task_manifest": task_manifest,
        "execution_fact": report_execution_item(task / "workspace", task_manifest),
        "origin": task_reg["origin"], "initial_manifest": task_reg["initial_manifest"],
        "executable": str(executable), "model": MODEL, "effort": "max", "settings": SETTINGS,
        "pins": {str(p.resolve()): file_hash(p) for p in paths},
        "items_sha256": digest(package["items"]), "shared_request": REQUEST,
        "presentation": presentation,
        "presented_items_sha256": digest(presentation_items(package, presentation)),
        "limits": {"turns": 1, "responses": 10, "phase_seconds": 180, "retries": 0},
        "review": ["Report claims match actual archived execution and its named scope",
                   "No invented current checks, copy identity, or exact evidence values",
                   "Task files unchanged; additional reads and all usage retained"],
        "boundary": "Historical binding is not adopted. Raw supplied items and native consumption are observed; no HostReceipt is asserted."}
    preflight(reg)
    save(area / "registration.json", reg)
    print({"registered": str(area), "model_calls": 0}, flush=True)


def run(area):
    reg = read(area / "registration.json")
    items = preflight(reg)
    save(area / "started.json", {"utc": datetime.now(timezone.utc).isoformat(), "automatic_reentry": False})
    opened, result = {}, {"status": "started", "cash": None}
    cell = area / "continuation"
    cell.mkdir()
    try:
        with NativeRPC(reg["executable"], cwd=reg["workspace"], stderr_path=area / "stderr.txt",
                       settings=SETTINGS) as server:
            save(area / "initialize.json", initialize(server))
            plugins = server.call("plugin/list", {"cwds": [reg["workspace"]], "forceRefetch": False}, timeout=45)
            skills = server.call("skills/list", {"cwds": [reg["workspace"]], "forceReload": False}, timeout=45)
            save(area / "discovery.json", {"plugins": plugins, "skills": skills})
            require(not plugins.get("marketplaceLoadErrors"), "native_plugin_discovery_failed")
            value = server.call("thread/start", {"cwd": reg["workspace"], "model": MODEL,
                "allowProviderModelFallback": False, "approvalPolicy": "never", "sandbox": "read-only",
                "runtimeWorkspaceRoots": [reg["workspace"]], "ephemeral": False, "dynamicTools": []}, timeout=40)
            opened["C"] = value
            save(cell / "thread-start.json", value)
            require(value["model"] == MODEL and value.get("reasoningEffort") == "max"
                    and value["sandbox"]["type"] == "readOnly" and value["approvalPolicy"] == "never",
                    "report_native_configuration_changed")
            import_items(server, value, items, cell)
            observed = observe(value, items)
            save(area / "admission.json", observed)
            require(observed["response_count"] == 0, "report_unregistered_prior_inference")
            preflight(reg)
            result["phase"] = phase(server, value, reg, cell, None, time.monotonic() + 180)
            audit_import(cell, items)
            result["host"] = audit_host(cell)
            result["status"] = "executed_review_pending"
    except Exception as exc:
        result.update(status="stopped", error=type(exc).__name__ + ":" + str(exc))
    finally:
        result["threads"] = archive_threads(area, opened)
        result["workspace_unchanged"] = manifest(reg["workspace"]) == reg["task_manifest"]
        save(area / "result.json", result)
    print({"status": result["status"], "workspace_unchanged": result["workspace_unchanged"]}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("area", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--presentation", choices=("covered", "recorded"), default="covered")
    args = parser.parse_args()
    if args.action == "prepare":
        require(all((args.source, args.task, args.executable)), "report_prepare_arguments_missing")
        prepare(args.area.resolve(), args.source.resolve(), args.task.resolve(), args.executable.resolve(),
                presentation=args.presentation)
    else:
        run(args.area.resolve())
