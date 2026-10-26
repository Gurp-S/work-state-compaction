"""C readiness evidence and a mandatory pre-inference gate for comparisons."""
from pathlib import Path
import time

from native_evidence import digest, file_hash, manifest, read, records, save, usage
from native_pair_workspace import preserve_arm


def require(value, reason):
    if not value:
        raise ValueError(reason)


def fingerprint(reg):
    fields = ("model", "effort", "settings", "dynamic_tools", "pins", "shared_request",
              "raw_source_items_sha256", "admission_warmup_threads", "orchestration")
    return digest({**{key: reg[key] for key in fields},
        "candidate_selection_sha256": (reg.get("candidate_selection") or {}).get("sha256"),
        "initial_manifest": digest(reg["initial_manifest"]),
        "continuation_caps": {key: reg["caps"][key] for key in
            ("responses_per_arm_including_compaction", "wall_seconds_per_arm", "model_requested_checks_per_arm")}})


def require_qualification(reg):
    purpose = reg.get("purpose")
    require(purpose in {"C_qualification", "comparison", "carrier_acquisition"}, "unregistered_experiment_purpose")
    if purpose == "carrier_acquisition":
        require(reg["order"] == ["compaction"] and reg["caps"]["native_compaction_calls"] == 1
                and reg["caps"]["pairs"] == 0 and bool(reg.get("study_workspace")),
                "acquisition_must_only_create_one_bound_native_checkpoint")
        return
    if purpose == "C_qualification":
        require(reg["order"] == ["C"] and reg["caps"]["native_compaction_calls"] == 0,
                "qualification_must_not_run_B")
        return
    reference = reg.get("qualification_receipt")
    require(reference, "C_qualification_required_before_comparison")
    path = Path(reference["path"])
    require(file_hash(path) == reference["sha256"], "C_qualification_receipt_changed")
    receipt = read(path)
    require(receipt.get("status") == "C_ready_for_registered_comparison", "C_qualification_not_ready")
    require(receipt["fingerprint"] == fingerprint(reg), "C_qualification_source_or_configuration_drift")
    required = {"registration.json", "result.json", "native-cwd-rehearsal.json",
                "C/artifact-outcome.json", "C/workspace-lifecycle.json",
                "C/continuation/import-audit.json", "native-rollout-archive/C.jsonl", "semantic-review.json"}
    if reg.get("candidate_selection"):
        required.update({"C/selection-audit.json", "reuse-review.json"})
    require(required <= receipt["evidence_sha256"].keys(), "C_qualification_evidence_incomplete")
    for relative, expected in receipt["evidence_sha256"].items():
        source = (path.parent / relative).resolve()
        source.relative_to(path.parent.resolve())
        require(file_hash(source) == expected, "C_qualification_evidence_changed:" + relative)
    require(digest(manifest(path.parent / "C/final-workspace")) == receipt["final_manifest_sha256"],
            "C_qualification_final_artifact_changed")


def rehearse_live_workspace(area, reg, server):
    """Exercise the real archive/reset path while all native threads retain cwd."""
    began = time.monotonic()
    work = Path(reg["workspace"]).resolve()
    require(server.proc.poll() is None, "native_server_not_running")
    require(manifest(work) == reg["initial_manifest"], "rehearsal_initial_source_changed")
    target = work / "python/scripts/_wsc_jsonl_source.py"
    target.resolve().relative_to(work)
    probe = work / ".native-workspace-lifecycle-probe"
    require(not probe.exists(), "rehearsal_probe_exists")
    before = target.read_bytes()
    with probe.open("xb") as stream:
        stream.write(b"Mechanical lifecycle rehearsal; no task-model output.\n")
    target.write_bytes(before + b"\n")
    archive = preserve_arm(area, "B", Path(reg["origin"]) / "frozen-workspace",
                           reg["initial_manifest"], restore_initial=True, rehearsal=True,
                           workspace=work if reg.get("study_workspace") else None)
    require(server.proc.poll() is None, "native_server_stopped_during_rehearsal")
    require(manifest(work) == reg["initial_manifest"], "rehearsal_did_not_restore_exact_start")
    result = {"passed": True, "server_process_id": server.proc.pid, "model_calls": 0,
        "source_restored_exactly": True, "new_file_removed": not probe.exists(),
        "synthetic_changes_only": True, "archive": archive, "seconds": time.monotonic() - began}
    save(area / "native-cwd-rehearsal.json", result)
    return result


def seal_qualification(area):
    """Seal actual C completion only after a separate final-report review exists."""
    area = Path(area).resolve()
    reg, result = read(area / "registration.json"), read(area / "result.json")
    require(reg["purpose"] == "C_qualification", "not_C_qualification")
    require(result["status"] == "C_qualification_executed_review_pending", "C_not_completed")
    require(not result["accounting_errors"] and result["original_workspace_unchanged"], "C_integrity_failed")
    outcome = result["arms"]["C"]
    require(outcome["completed"] and not outcome["failure"] and outcome["usage_complete"], "C_execution_failed")
    artifact = read(area / "C/artifact-outcome.json")
    require(artifact["groups"] == {"business": {"passed": 13, "total": 13},
        "owned_regression": {"passed": 5, "total": 5}}, "C_quality_failed")
    require(not artifact["protected_changes"] and bool(artifact["finals"]), "C_delivery_incomplete")
    require(manifest(area / "C/final-workspace") == artifact["final_manifest"], "C_artifact_drift")
    require(read(area / "C/continuation/import-audit.json")["matched"], "C_import_not_verified")
    require(read(area / "native-cwd-rehearsal.json")["passed"], "C_lifecycle_not_verified")
    review = read(area / "semantic-review.json")
    require(review["verdict"] == "supported_within_named_scope" and
            review["finals_sha256"] == digest(artifact["finals"]) and
            review["current_check_run_id"] == artifact["current_check_run_id"], "C_final_report_not_reviewed")
    if reg.get("candidate_selection"):
        reuse = read(area / "reuse-review.json")
        require(reuse["verdict"] == "bound_observations_reused_without_stale_lookup" and
                reuse["selection_sha256"] == reg["candidate_selection"]["sha256"] and
                reuse["events_sha256"] == file_hash(area / "C/continuation/events.jsonl") and
                reuse["finals_sha256"] == digest(artifact["finals"]), "C_evidence_reuse_not_reviewed")
    for name, evidence in result["all_thread_evidence"].items():
        from native_rollout_snapshot import capture_rollout
        snapshot = capture_rollout(area / "native-rollout-archive" / (name + ".jsonl"))
        require(snapshot.metadata["parse_complete"] and
                snapshot.metadata["sha256"] == evidence["sha256"], "C_usage_archive_incomplete_or_changed")
        receipt = usage(snapshot.rows, evidence["receipts"]["thread_id"], line_numbers=snapshot.line_numbers)
        require(receipt == evidence["receipts"], "C_usage_changed")
        require(receipt["response_count"] > 0 if name == "C" else receipt["response_count"] == 0,
                "qualification_inference_scope_changed")
    for path, expected in reg["pins"].items():
        require(file_hash(path) == expected, "qualification_source_changed:" + path)
    require(manifest(Path(reg["origin"]) / "frozen-workspace") == reg["initial_manifest"], "frozen_source_changed")
    require(manifest(Path(reg["origin"]) / "workspace") == reg["original_workspace_manifest"], "origin_changed")
    evidence = {}
    for path in sorted(area.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(area)
        if (relative.parts[0] == "workspace" or "final-workspace" in relative.parts
                or "rehearsal-workspace" in relative.parts or "__pycache__" in relative.parts):
            continue
        evidence[relative.as_posix()] = file_hash(path)
    receipt = {"status": "C_ready_for_registered_comparison", "purpose": "qualification_only_not_comparison",
        "fingerprint": fingerprint(reg), "evidence_sha256": evidence,
        "final_manifest_sha256": digest(artifact["final_manifest"]),
        "responses": outcome["receipts"]["response_count"], "cash": None,
        "scope": "This pinned task, native configuration and runner; not a universal reliability guarantee."}
    save(area / "qualification.json", receipt)
    return receipt
