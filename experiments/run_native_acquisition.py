"""One actual compaction in the stable study workspace, before C qualification."""
from datetime import datetime, timezone
from pathlib import Path
import time

import run_native_pair as driver
from native_c_qualification import require_qualification
from native_evidence import digest, file_hash, manifest, read, save
from native_thread_archive import archive_threads


def run(area):
    area = Path(area).resolve()
    reg = read(area / "registration.json")
    driver.require(reg["purpose"] == "carrier_acquisition", "not_native_acquisition")
    require_qualification(reg)
    driver.verify_pins(reg)
    work, origin = Path(reg["workspace"]), Path(reg["origin"])
    driver.require(manifest(work) == reg["initial_manifest"], "acquisition_start_changed")
    driver.require(manifest(origin / "workspace") == reg["original_workspace_manifest"], "original_workspace_changed")
    save(area / "started.json", {"utc": datetime.now(timezone.utc).isoformat(), "automatic_reentry": False,
                                "scope": "one_native_compaction_no_continuation"})
    began, opened = time.monotonic(), {}
    summary = {"status": "running", "cash": None, "new_model_response_count": None}
    cell, server_cell = area / "B/compaction", area / "retained-server"
    try:
        cell.mkdir(parents=True, exist_ok=False)
        server_cell.mkdir()
        source = read(origin / "common-native-source.json")
        controls = [i for i in source["items"] if i.get("role") in {"system", "developer", "user"}]
        items = source["items"] + [reg["common_workspace_fact"]]
        save(cell / "installed-items.json", items)
        with driver.open_server(reg, server_cell) as server:
            save(server_cell / "initialize.json", driver.initialize(server))
            plugins = server.call("plugin/list", {"cwds": [str(work)], "forceRefetch": False}, timeout=45)
            skills = server.call("skills/list", {"cwds": [str(work)], "forceReload": False}, timeout=45)
            save(server_cell / "discovery.json", {"plugins": plugins, "skills": skills})
            driver.require(not plugins.get("marketplaceLoadErrors"), "native_plugin_discovery_failed")
            driver.require(reg["admission_warmup_threads"] == 1, "acquisition_warmup_policy_changed")
            warmup = area / "bootstrap-warmup"
            warmup.mkdir()
            opened["warmup"] = driver.start(server, reg, warmup)
            driver.import_items(server, opened["warmup"], controls, warmup)
            opened["compaction"] = driver.start(server, reg, cell)
            driver.import_items(server, opened["compaction"], items, cell)
            outcome = driver.phase(server, opened["compaction"], reg, cell, None, began + 480, compact=True)
            summary["native_compaction"] = outcome
            driver.ensure_phase(outcome)
            driver.require(outcome["completed"], "native_acquisition_incomplete")
            driver.audit_import(cell, items)
            driver.audit_host(cell)
        driver.verify_pins(reg)
        driver.require(manifest(work) == reg["initial_manifest"], "acquisition_workspace_changed")
        driver.require(manifest(origin / "workspace") == reg["original_workspace_manifest"], "original_workspace_changed")
        summary["status"] = "native_checkpoint_acquired"
    except Exception as exc:
        summary["status"] = "stopped"
        summary["stop_reason"] = type(exc).__name__ + ":" + str(exc)
    finally:
        evidence = archive_threads(area, opened)
        summary["all_thread_evidence"] = evidence
        summary["new_model_response_count"] = sum(v.get("receipts", {}).get("response_count", 0) for v in evidence.values())
        summary["accounting_errors"] = [name for name, value in evidence.items() if "accounting_error" in value]
        if summary["accounting_errors"]:
            summary["status"] = "stopped"
            summary.setdefault("stop_reason", "thread_evidence_incomplete")
        if summary["status"] == "native_checkpoint_acquired":
            counts = {name: value["receipts"]["response_count"] for name, value in evidence.items()}
            if counts != {"warmup": 0, "compaction": 1}:
                summary.update(status="stopped", stop_reason="acquisition_response_scope_changed")
        summary["total_runner_seconds"] = time.monotonic() - began
        save(area / "result.json", summary)
    if summary["status"] == "native_checkpoint_acquired":
        canonical = read(cell / "canonical-state.json")["items"]
        carriers = [item for item in canonical if item.get("type") == "compaction"]
        driver.require(len(carriers) == 1, "native_acquisition_carrier_missing")
        paths = [area / "registration.json", origin / "common-native-source.json",
                 *(cell / name for name in ("installed-items.json", "rollout.jsonl", "phase-outcome.json",
                                           "canonical-state.json", "import-audit.json"))]
        proof = {"source_items_sha256": digest(source["items"]), "carrier_sha256": digest(carriers[0]),
                 "workspace": str(work), "pins": {str(path): file_hash(path) for path in paths},
                 "opaque_decoded": False, "native_import_check": "performed_again_before_C_inference",
                 "acquisition_response_count": 1}
        save(area / "carrier-proof.json", proof)
    print({key: summary.get(key) for key in ("status", "new_model_response_count", "total_runner_seconds", "stop_reason")}, flush=True)
