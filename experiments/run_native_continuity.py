"""One bounded native task/driver qualification, not a WSC benefit comparison."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

from native_continuity_checks import aggregate, archive_workspace, grade, prior_check_fact, require
from native_evidence import digest, file_hash, manifest, read, save
from native_pair_admission import observe
from native_thread_archive import archive_threads
from run_native_pair import MODEL, SETTINGS, NativeRPC, initialize, import_items, phase, verify_pins

HERE = Path(__file__).resolve().parent
PURPOSE = "continuity_task_diagnostic_not_comparison"


def execution_item(workspace, stage, current, prior):
    fact = {"kind": "continuous_task_execution", "current_workspace": str(Path(workspace).resolve()),
            "current_file_manifest_sha256": digest(current), "execution_mode": "workspace_write",
            "stage_id": stage["id"], "stage_request_sha256": digest(stage["message"]),
            "prior_acceptance": prior}
    return {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": json.dumps(fact, ensure_ascii=False, sort_keys=True)}]}


def preflight(reg):
    verify_pins(reg)
    package = read(reg["package"])
    require(package["status"] == "prepared_not_executed", "continuity_package_status_changed")
    require([s["id"] for s in package["stages"]] == ["revision", "explicit_identity", "handoff"],
            "continuity_stage_protocol_changed")
    require(file_hash(package["baseline_archive"]) == package["baseline_archive_sha256"],
            "continuity_baseline_archive_changed")
    require(file_hash(reg["grader"]) == package["grader_sha256"], "continuity_grader_changed")
    return package


def prepare(area, package_path, executable):
    require(not area.exists(), "continuity_study_already_exists")
    package = read(package_path)
    require(file_hash(package["baseline_archive"]) == package["baseline_archive_sha256"],
            "continuity_baseline_archive_changed")
    grader = HERE.parent / "tests" / package["grader_file"]
    require(file_hash(grader) == package["grader_sha256"], "continuity_grader_changed")
    area.mkdir()
    frozen = area / "frozen-workspace"
    frozen.mkdir()
    # Validate ZIP members against the frozen manifest before extracting them.
    with zipfile.ZipFile(package["baseline_archive"]) as archive:
        require(len(archive.namelist()) == len(package["baseline_source_sha256"])
                and set(archive.namelist()) == set(package["baseline_source_sha256"]),
                "continuity_baseline_members_changed")
        for name in archive.namelist():
            target = (frozen / name).resolve()
            require(target.is_relative_to(frozen.resolve()), "continuity_archive_path_escape")
        archive.extractall(frozen)
    require(manifest(frozen) == package["baseline_source_sha256"], "continuity_baseline_bytes_changed")
    # Use the user's actual repository rules, not experiment-authored instructions.
    shutil.copy2(HERE.parents[1] / "AGENTS.md", frozen / "AGENTS.md")
    shutil.copytree(frozen, area / "workspace")
    pins = [package_path, Path(package["baseline_archive"]), grader, executable,
            HERE.parents[1] / "AGENTS.md"]
    pins += [p for folder in ("src", "tests", "experiments") for p in (HERE.parent / folder).rglob("*.py")]
    config = Path.home() / ".codex" / "config.toml"
    if config.exists():
        pins.append(config)
    reg = {"purpose": PURPOSE, "registered_utc": datetime.now(timezone.utc).isoformat(),
           "origin": str(area), "workspace": str(area / "workspace"), "package": str(package_path),
           "grader": str(grader), "executable": str(executable), "model": MODEL,
           "effort": "max", "settings": SETTINGS, "initial_manifest": manifest(frozen),
           "pins": {str(p.resolve()): file_hash(p) for p in pins},
           "limits": {"stages": 3, "responses_per_stage_including_compaction": 10,
                      "seconds_per_stage": 180, "automatic_retries": 0, "forced_compactions": 0},
           "stop": "Any task failure, execution failure, unknown usage or cap stops later stages. No retry.",
           "scope": "Native continuous task and driver qualification only; no C or benefit comparison.",
           "cash": None}
    preflight(reg)
    baseline = grade(area / "workspace", grader, "RevisionContractTests", area / "baseline-check")
    require(baseline["tests"] == 6 and len(baseline["failures"]) == 5 and not baseline["errors"],
            "continuity_baseline_diagnostic_changed")
    save(area / "registration.json", reg)
    print(json.dumps({"registered": str(area), "model_calls": 0}), flush=True)


def run(area):
    reg = read(area / "registration.json")
    package = preflight(reg)
    require(manifest(reg["workspace"]) == reg["initial_manifest"], "continuity_start_workspace_changed")
    # Exclusive save prevents reentry after any prior attempt, including failures.
    save(area / "started.json", {"utc": datetime.now(timezone.utc).isoformat(), "reentry": False})
    result, opened, phases = {"status": "started", "stages": [], "cash": None}, {}, []
    prior = None
    try:
        with NativeRPC(reg["executable"], cwd=reg["workspace"], stderr_path=area / "stderr.txt", settings=SETTINGS) as server:
            save(area / "initialize.json", initialize(server))
            plugins = server.call("plugin/list", {"cwds": [reg["workspace"]], "forceRefetch": False}, timeout=45)
            skills = server.call("skills/list", {"cwds": [reg["workspace"]], "forceReload": False}, timeout=45)
            save(area / "discovery.json", {"plugins": plugins, "skills": skills})
            require(not plugins.get("marketplaceLoadErrors"), "native_plugin_discovery_failed")
            value = server.call("thread/start", {"cwd": reg["workspace"], "model": MODEL,
                "allowProviderModelFallback": False, "approvalPolicy": "never", "sandbox": "workspace-write",
                "runtimeWorkspaceRoots": [reg["workspace"]], "ephemeral": False, "dynamicTools": []}, timeout=40)
            opened["native"] = value
            save(area / "thread-start.json", value)
            require(value["model"] == MODEL and value.get("reasoningEffort") == "max"
                    and value["sandbox"]["type"] == "workspaceWrite" and value["approvalPolicy"] == "never",
                    "continuity_native_configuration_changed")
            for index, stage in enumerate(package["stages"]):
                preflight(reg)
                cell = area / "stages" / stage["id"]
                cell.mkdir(parents=True)
                before = archive_workspace(reg["workspace"], cell / "before.zip")
                if index:
                    require(before["manifest"] == result["stages"][-1]["after"]["manifest"],
                            "continuity_interstage_source_changed")
                fact = execution_item(reg["workspace"], stage, before["manifest"], prior)
                stage_reg = {**reg, "shared_request": stage["message"], "execution_fact": fact,
                             "accounting_scope": "append_only_turn" if index else "fresh_single_turn"}
                save(cell / "registration.json", stage_reg)
                import_items(server, value, [fact], cell)
                if index == 0:
                    admission = observe(value, [fact])
                    save(area / "admission.json", admission)
                    require(admission["response_count"] == 0, "continuity_unregistered_prior_inference")
                require(manifest(reg["workspace"]) == before["manifest"], "continuity_prephase_source_changed")
                outcome = phase(server, value, stage_reg, cell, None, time.monotonic() + 180)
                phases.append(outcome)
                after = archive_workspace(reg["workspace"], cell / "after.zip")
                entry = {"stage_id": stage["id"], "before": before, "after": after,
                         "phase_outcome": str(cell / "phase-outcome.json")}
                result["stages"].append(entry)
                require(outcome["completed"] and not outcome["failure"] and outcome.get("usage_complete"),
                        "continuity_stage_incomplete")
                require(after["manifest"].get("AGENTS.md") == reg["initial_manifest"]["AGENTS.md"],
                        "continuity_project_rules_changed")
                if index < 2:
                    receipt = grade(reg["workspace"], reg["grader"], stage["acceptance_class"], cell / "acceptance")
                    entry["acceptance"] = prior_check_fact(receipt, cell / "acceptance" / "receipt.json")
                    require(receipt["passed"], "continuity_task_acceptance_failed")
                    prior = entry["acceptance"]
                else:
                    require(after["manifest"] == before["manifest"], "continuity_handoff_changed_source")
                    entry["acceptance"] = {"carried_current_receipt": prior, "semantic_review": "pending"}
                save(cell / "stage-result.json", entry)
            result["status"] = "executed_semantic_review_pending"
    except Exception as exc:
        result.update(status="stopped", error=type(exc).__name__ + ":" + str(exc))
    finally:
        result["threads"] = archive_threads(area, opened)
        try:
            result["usage"] = aggregate(phases)
            native = result["threads"].get("native", {})
            receipts = native.get("receipts")
            result["archive_matches_stage_usage"] = bool(receipts and
                receipts["all_usage"] == result["usage"]["known_usage"] and
                sorted(r["response_id"] for r in receipts["response_receipts"]) == result["usage"]["response_ids"])
            if not result["archive_matches_stage_usage"] or native.get("accounting_error"):
                result["usage"].update(complete=False, complete_usage=None)
                result.update(status="stopped", accounting_error="continuity_final_archive_mismatch_or_incomplete")
        except Exception as exc:
            result.update(status="stopped", accounting_error=str(exc))
        save(area / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
                      "usage": result.get("usage")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("area", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        require(args.package is not None and args.executable is not None, "continuity_prepare_arguments_missing")
        prepare(args.area.resolve(), args.package.resolve(), args.executable.resolve())
    else:
        run(args.area.resolve())
