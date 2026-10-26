"""Opt-in retained-process orchestration for the existing registered B/C study."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import time

import run_native_pair as driver
from native_evidence import (digest, file_hash, import_evidence, manifest, read,
                             records, save, usage)
from native_pair_admission import PairAdmission, observe
from native_pair_workspace import preserve_arm
from native_thread_archive import archive_threads
from native_c_qualification import rehearse_live_workspace, require_qualification


def append_material(server, opened, controls, suffix, cell):
    full = controls + suffix
    save(cell / "installed-items.json", full)
    response = server.call("thread/inject_items", {"threadId": opened["thread"]["id"], "items": suffix})
    actual = [r["payload"] for r in records(opened["thread"]["path"]) if r["type"] == "response_item"]
    evidence = import_evidence(actual, full)
    save(cell / "material-import-audit.json", {**evidence, "rpc_result": response,
                                              "supplied_sha256": digest(full)})
    driver.require(evidence["matched"], "split_import_changed_original_material")
    return full


def protect_origin(reg):
    driver.verify_pins(reg)
    driver.require(manifest(Path(reg["origin"]) / "workspace") == reg["original_workspace_manifest"],
                   "original_research_workspace_changed")


def run(area):
    reg = read(area / "registration.json")
    require_qualification(reg)
    driver.verify_pins(reg)
    qualification = reg["purpose"] == "C_qualification"
    protect_origin(reg)
    work, origin = Path(reg["workspace"]), Path(reg["origin"])
    driver.require(manifest(work) == reg["initial_manifest"], "starting_workspace_changed")
    save(area / "started.json", {"utc": datetime.now(timezone.utc).isoformat(), "automatic_reentry": False,
                                "orchestration": reg["orchestration"]})
    began = time.monotonic()
    summary = {"status": "running", "arms": {}, "cash": None, "verdict": None,
        "shared_historical_diagnostic": reg["shared_historical_diagnostic"],
        "shared_historical_diagnostic_model": reg["historical_diagnostic_model"]}
    opened = {}
    try:
        source = read(origin / "common-native-source.json")
        controls = [i for i in source["items"] if i.get("role") in {"user", "system", "developer"}]
        driver.require(source["items"][:len(controls)] == controls, "source_controls_not_prefix")
        candidate = driver.prepare_candidate(area, reg, source)
        driver.require(candidate[:len(controls)] == controls, "candidate_controls_not_original_prefix")
        cells = {"compaction": area / "B/compaction", "B": area / "B/continuation", "C": area / "C/continuation"}
        for cell in cells.values():
            cell.mkdir(parents=True, exist_ok=False)
        server_cell = area / "retained-server"
        server_cell.mkdir()
        checker = driver.Checker(file_hash(work / driver.TARGETS[3]))
        with driver.open_server(reg, server_cell) as server:
            save(server_cell / "initialize.json", driver.initialize(server))
            # Await normal read-only discovery before any experimental thread starts.
            plugins = server.call("plugin/list", {"cwds": [str(work)], "forceRefetch": False}, timeout=45)
            skills = server.call("skills/list", {"cwds": [str(work)], "forceReload": False}, timeout=45)
            save(server_cell / "discovery.json", {"plugins": plugins, "skills": skills})
            driver.require(not plugins.get("marketplaceLoadErrors"), "native_plugin_discovery_failed")
            # One preregistered, inference-free native bootstrap warms the
            # separate recommended-plugin discovery. No adaptive thread retries.
            driver.require(reg.get("admission_warmup_threads") == 1, "warmup_policy_unregistered")
            warmup_cell = area / "bootstrap-warmup"
            warmup_cell.mkdir()
            opened["warmup"] = driver.start(server, reg, warmup_cell)
            driver.import_items(server, opened["warmup"], controls, warmup_cell)
            warmup_observation = observe(opened["warmup"], controls)
            driver.require(warmup_observation["response_count"] == 0, "warmup_inference_detected")
            save(warmup_cell / "observation.json", warmup_observation)
            for name, cell in cells.items():
                opened[name] = driver.start(server, reg, cell)
                driver.import_items(server, opened[name], controls, cell)
            observations = lambda: {name: observe(opened[name], controls) for name in cells}
            observed = observations()
            save(area / "paired-admission-observations.json", observed)
            gate = PairAdmission(observed)
            rehearse_live_workspace(area, reg, server)
            admission_seconds = time.monotonic() - began
            save(area / "paired-admission.json", {"admitted": True, "inference_calls": 0,
                "shared_host_sha256": digest(observed["B"]["host"]), "seconds": admission_seconds,
                "server_process_id": server.proc.pid, "members": {n: v["thread_id"] for n, v in observed.items()},
                "prompt_overrides": False, "plugin_configuration_changes": False})
            print({"paired_admission": True, "inference_calls": 0, "seconds": admission_seconds}, flush=True)
            candidate_items = append_material(server, opened["C"], controls,
                candidate[len(controls):] + [reg["common_workspace_fact"]], cells["C"])
            b_begin = time.monotonic()
            # Common admission is charged equally to both arms' wall budgets.
            deadline = b_begin + 480 - admission_seconds
            protect_origin(reg)
            native_carrier = None
            if reg.get("native_carrier"):
                from native_carrier_source import load_carrier
                native_carrier = load_carrier(read(reg["candidate_selection"]["path"]), source)
                driver.require(native_carrier["carrier_sha256"] == reg["native_carrier"]["carrier_sha256"],
                               "registered_carrier_changed")
                summary["shared_native_compaction"] = reg["native_carrier"]
            if qualification:
                sequence = (("C", candidate_items),)
            else:
                require_qualification(reg)
                if native_carrier is None:
                    compact_items = append_material(server, opened["compaction"], controls,
                        source["items"][len(controls):] + [reg["common_workspace_fact"]], cells["compaction"])
                    compact = gate.execute("compaction", observations(), lambda: driver.phase(server, opened["compaction"],
                        reg, cells["compaction"], checker, deadline, compact=True))
                    summary["native_compaction"] = compact
                    driver.ensure_phase(compact)
                    driver.require(compact["completed"], "native_compaction_incomplete")
                    driver.audit_import(cells["compaction"], compact_items)
                    history = read(cells["compaction"] / "canonical-state.json")["items"]
                    opaque = [item for item in history if item["type"] == "compaction"]
                else:
                    opaque = [native_carrier["item"]]
                    history = controls + opaque
                driver.require(len(opaque) == 1, "native_compaction_artifact_missing")
                b_items = append_material(server, opened["B"], controls, opaque + [reg["common_workspace_fact"]], cells["B"])
                save(area / "B/control-normalization.json", {"original_control_sha256": digest(controls),
                    "opaque_compaction_sha256": digest(opaque),
                    "policy": "Same unchanged original controls as C. Native generated bootstrap is retained from joint admission.",
                    "compactor_plaintext_controls": [i for i in history if i.get("role") in {"user", "system", "developer"}]})
                sequence = (("B", b_items), ("C", candidate_items))
            for arm, material in sequence:
                protect_origin(reg)
                driver.require(manifest(work) == reg["initial_manifest"], "arm_initial_source_changed")
                if arm == "C":
                    arm_begin = time.monotonic()
                    deadline = arm_begin + 480 - admission_seconds
                else:
                    arm_begin = b_begin
                spent = (native_carrier["shared_acquisition_receipts"]["response_count"] if native_carrier else
                         compact["receipts"]["response_count"] if arm == "B" else 0)
                outcome = gate.execute(arm, observations(), lambda: driver.phase(server, opened[arm], reg,
                    cells[arm], checker, deadline, spent_responses=spent))
                summary["arms"][arm] = outcome
                driver.ensure_phase(outcome)
                driver.audit_import(cells[arm], material)
                host = driver.audit_host(cells[arm])
                if arm == "C" and not qualification:
                    driver.require(host == read(cells["B"] / "host-audit.json"), "runtime_native_host_drift")
                driver.audit_workspace(area, arm, reg, outcome, checker)
                protect_origin(reg)
                preserve_arm(area, arm, origin / "frozen-workspace", reg["initial_manifest"],
                             restore_initial=arm == "B" or (qualification and bool(reg.get("study_workspace"))),
                             workspace=work if reg.get("study_workspace") else None)
                outcome["arm_seconds_including_shared_admission"] = time.monotonic() - arm_begin + admission_seconds
            driver.verify_pins(reg)
            summary["status"] = "C_qualification_executed_review_pending" if qualification else "pair_executed_review_pending"
    except Exception as exc:
        summary["status"] = "stopped"
        summary["stop_reason"] = type(exc).__name__ + ":" + str(exc)
    finally:
        # Preserve no-inference threads and any interrupted/failed response records too.
        evidence = archive_threads(area, opened)
        summary["all_thread_evidence"] = evidence
        summary["new_model_response_count"] = sum(v.get("receipts", {}).get("response_count", 0) for v in evidence.values())
        summary["accounting_errors"] = [n for n, v in evidence.items() if "accounting_error" in v]
        if summary["accounting_errors"]:
            summary["status"] = "stopped"
            summary.setdefault("stop_reason", "thread_evidence_incomplete")
        summary["new_model_response_count_scope"] = "observed_unique_receipts_not_inferred_missing_usage"
        summary["original_workspace_unchanged"] = manifest(origin / "workspace") == reg["original_workspace_manifest"]
        summary["total_runner_seconds"] = time.monotonic() - began
        save(area / "result.json", summary)
    print({k: summary[k] for k in ("status", "new_model_response_count", "total_runner_seconds")}, flush=True)
    if summary.get("stop_reason"):
        print(summary["stop_reason"], flush=True)
