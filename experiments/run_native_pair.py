"""One registered, bounded native B / independent-WSC C recovery experiment.

Explicit checkpoint imports are measured using the native RPC and rollout.
This does not claim the stronger transactional HostPort installation contract.
The WSC export remains ready: no fabricated HostReceipt advances its cursor.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import time

from native_rpc import NativeRPC
from native_evidence import (contains_sequence, import_evidence, digest, file_hash, manifest,
                             python_manifest, read, records, save, state, usage)
from native_rollout_snapshot import capture_rollout
from native_phase_budget import PhaseBudget
from native_usage_boundary import completion_evidence
from benefit_checks import APP, Checker, TARGETS, dependencies

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from wsc import WSC, Store, Limits, Selection, Understanding
from wsc.adapters.codex import CodexCheckpointAdapter

MODEL = "gpt-6-luna"
SETTINGS = ["features.multi_agent=false", 'model_reasoning_effort="max"']
TOOL = {"type": "function", "name": "RunChecks", "description":
        "Runs 13 named source-fidelity cases and the existing five owned unittest tests against current source in private synthetic fixtures. Returns individual observations, source identities and exact scope; no model calls.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
CAPS = {"pairs": 1, "responses_per_arm_including_compaction": 10,
        "wall_seconds_per_arm": 480, "model_requested_checks_per_arm": 3,
        "native_compaction_calls": 1, "native_compaction_wall_seconds": 240}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify_pins(reg):
    for p, h in reg["pins"].items():
        require(file_hash(p) == h, "registered_input_changed:" + p)
    require(manifest(Path(reg["origin"]) / "frozen-workspace") == reg["initial_manifest"],
            "frozen_workspace_changed")


def register(origin, area, executable, *, paired_admission=False, purpose="comparison", qualification=None,
             candidate_selection=None, study_workspace=None):
    require(paired_admission, "paired_admission_required_for_new_experiments")
    require(purpose in {"C_qualification", "comparison", "carrier_acquisition"}, "invalid_experiment_purpose")
    require(purpose != "comparison" or qualification is not None,
            "C_qualification_required_before_comparison")
    require(purpose != "carrier_acquisition" or study_workspace is not None,
            "acquisition_requires_stable_study_workspace")
    require(candidate_selection is not None, "registered_evidence_selection_required")
    area.mkdir(parents=True, exist_ok=False)
    prior = read(origin / "registration-v2.json")
    source = read(origin / "common-native-source.json")
    frozen = origin / "frozen-workspace"
    require(python_manifest(frozen) == prior["initial_python_manifest"], "frozen_python_source_drift")
    require(len(source["items"]) == 20 and source["items"][-1].get("phase") == "final_answer",
            "not_registered_pre_repair_boundary")
    from native_candidate_evidence import selected_material
    plan, _, selection, _ = selected_material(candidate_selection, source)
    initial = manifest(frozen)
    study_receipt = None
    if study_workspace is not None:
        from native_study_workspace import validate
        work, study_receipt = validate(area, study_workspace, frozen, initial, require_initial=True)
    else:
        work = area / "workspace"
    carrier = None
    if plan.get("presentation") == "native_carrier_facts_v1":
        require(purpose != "carrier_acquisition", "acquisition_requires_original_source")
        from native_carrier_source import load_carrier
        carrier = load_carrier(plan, source)
        require(carrier["model"] == MODEL and carrier["effort"] == "max", "carrier_model_configuration_mismatch")
        require(Path(carrier["workspace"]).resolve() == work.resolve(),
                "native_carrier_workspace_mismatch")
    if study_workspace is None:
        shutil.copytree(frozen, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    require(manifest(work) == initial, "workspace_copy_mismatch")
    pins = [origin / "common-native-source.json", origin / "registration-v2.json",
            origin / "diagnostic/phase-outcome.json", Path(source["rollout_path"]),
            Path(candidate_selection), Path(executable), *dependencies(),
            *(Path(e.current_resource) for e in selection.excerpts if e.current_resource is not None),
            *HERE.glob("*.py"), *(HERE.parent / "src").rglob("*.py")]
    pins.extend(Path(ref["path"]) for ref in plan.get("generated_selection", {}).get("evidence", {}).values())
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        pins.append(config)
    if carrier is not None:
        pins.extend(Path(path) for path in carrier["pins"])
    if study_receipt is not None:
        pins.append(study_receipt)
    relocation = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text":
        json.dumps({"kind": "experimental_workspace_binding", "historical_workspace": str(origin / "workspace"),
            "current_workspace": str(work), "initial_file_manifest_sha256": digest(initial),
            "source_history": "Unmodified historical observations; historical absolute workspace paths refer to the original observation location.",
            "current_file_mapping": "Same relative paths under current_workspace contain the registered pre-repair file bytes.",
            "execution_write_scope": str(work),
            **({"native_compaction_workspace": carrier["workspace"],
                "native_compaction_source": "Same pre-repair source items; the carried native checkpoint was generated in native_compaction_workspace."}
               if carrier else {})}, ensure_ascii=False, sort_keys=True)}]}
    baseline = Checker(file_hash(work / TARGETS[3])).run(work, area / "baseline-check")
    require(baseline["groups"] == {"business": {"passed": 9, "total": 13},
                                   "owned_regression": {"passed": 2, "total": 5}}, "baseline_changed")
    require(manifest(work) == initial, "baseline_changed_inputs")
    reg = {"registered_utc": datetime.now(timezone.utc).isoformat(), "origin": str(origin),
        "workspace": str(work), "executable": str(executable), "model": MODEL, "effort": "max",
        "settings": SETTINGS, "dynamic_tools": [TOOL],
        "caps": {**CAPS, **({"pairs": 0, "native_compaction_calls": 0} if purpose == "C_qualification" else {}),
                 **({"pairs": 0, "native_compaction_calls": 1} if purpose == "carrier_acquisition" else {}),
                 **({"native_compaction_calls": 0} if carrier else {})},
        "order": ["compaction"] if purpose == "carrier_acquisition" else ["C"] if purpose == "C_qualification" else ["B", "C"], "purpose": purpose,
        "pins": {str(p.resolve()): file_hash(p) for p in pins}, "initial_manifest": initial,
        "shared_request": prior["continuation_request"], "common_workspace_fact": relocation,
        "raw_source_items_sha256": digest(source["items"]), "raw_source_items": 20,
        "shared_historical_diagnostic": read(origin / "diagnostic/phase-outcome.json")["receipts"],
        "historical_diagnostic_model": prior["model"], "baseline_groups": baseline["groups"],
        "path_policy": "Both arms use the same new cwd and workspace-write sandbox; original history is immutable. A common factual relocation record is added to both. Original research workspace hashes are checked after every phase.",
        "original_workspace_manifest": manifest(origin / "workspace"),
        "acceptance": ["Current 13 business and 5 owned regression cases", "Protected and unrelated initial files unchanged",
            "Final report faithful to current artifact and verification scope", "Complete unique response receipts including native compaction"],
        "stop": "Source/config drift, unknown usage or infrastructure failure stops the pair. Caps never extended. No single-arm retry.",
        "cost_policy": "Charge historical shared diagnosis to each arm; record its original model. New B compaction uses luna. All new response receipts, checks, failures and elapsed time count. Prices remain unknown.",
        "limitations": ["No continuous native A", "One selected task and one recovery", "Explicit reuse of an existing diagnosis, not automatic selection",
            "Native RPC checkpoint import is not the full transactional WSC HostPort installation contract",
            "No claim of exact provider wire visibility; accepted native import and durable rollout are audited separately"],
        "new_inference_calls": 0, "cash": None,
        "paired_admission": paired_admission,
        "admission_warmup_threads": 1 if paired_admission else 0,
        "automatic_admission_retries": 0,
        "orchestration": "retained_pair_native_carrier_binding_v1" if carrier else "retained_pair_bound_observations_v5",
        "candidate_selection": {"path": str(candidate_selection.resolve()),
                                "sha256": file_hash(candidate_selection)},
        "qualification_receipt": {"path": str(qualification.resolve()), "sha256": file_hash(qualification)}
                                 if qualification else None}
    if study_receipt is not None:
        reg["study_workspace"] = {"ownership_receipt": str(study_receipt), "sha256": file_hash(study_receipt),
                                  "stable_workspace": str(work), "qualification_restores_initial": True}
    if carrier is not None:
        reg["native_carrier"] = {k: carrier[k] for k in
            ("carrier_sha256", "thread_id", "workspace", "observed_at", "shared_acquisition_receipts")}
        reg["cost_policy"] = ("Both arms retain the same previously acquired native checkpoint. Its recorded acquisition cost and the original diagnosis are attributed equally to both; new inference is counted separately. All preparation, failures and unknown parent selection cost remain recorded. Prices unknown.")
        reg["limitations"].append("Native checkpoint plus one version-bound reference addendum; not a replacement compactor or general automatic WSC selection")
    from native_c_qualification import require_qualification
    require_qualification(reg)
    save(area / "registration.json", reg)
    print(json.dumps({"registered": str(area), "baseline": baseline["groups"], "inference_calls": 0}), flush=True)


def open_server(reg, cell):
    return NativeRPC(reg["executable"], cwd=reg["workspace"], stderr_path=cell / "stderr.txt", settings=SETTINGS)


def initialize(server):
    result = server.call("initialize", {"clientInfo": {"name": "independent_wsc_pair", "version": "0.1"},
                                        "capabilities": {"experimentalApi": True}}, timeout=40)
    server.send({"method": "initialized"})
    return result


def start(server, reg, cell):
    result = server.call("thread/start", {"cwd": reg["workspace"], "model": MODEL,
        "allowProviderModelFallback": False, "approvalPolicy": "never", "sandbox": "workspace-write",
        "runtimeWorkspaceRoots": [reg["workspace"]], "ephemeral": False, "dynamicTools": [TOOL]}, timeout=40)
    save(cell / "thread-start.json", result)
    require(result["model"] == MODEL and result.get("reasoningEffort") == "max", "model_configuration_mismatch")
    require(result["sandbox"]["type"] == "workspaceWrite", "sandbox_configuration_mismatch")
    require(result["approvalPolicy"] == "never", "approval_configuration_mismatch")
    return result


def import_items(server, opened, items, cell):
    save(cell / "imported-items.json", items)
    response = server.call("thread/inject_items", {"threadId": opened["thread"]["id"], "items": items}, timeout=30)
    save(cell / "import-rpc-receipt.json", {"result": response, "items_sha256": digest(items),
        "evidence_scope": "Native RPC accepted these items; model consumption is not inferred from acceptance alone."})
    # The real inject operation flushes its native rollout even without inference.
    rows = records(opened["thread"]["path"])
    evidence = import_evidence([r["payload"] for r in rows if r["type"] == "response_item"], items)
    save(cell / "pre-inference-import-audit.json", evidence)
    require(evidence["matched"], "native_import_changed_supplied_fields")
    meta = next(r["payload"] for r in rows if r["type"] == "session_meta")
    initial = [r["payload"] for r in rows if r["type"] == "response_item"][:evidence["start_ordinal"]]
    host = {"base_instructions_sha256": digest(meta["base_instructions"]),
        "dynamic_tools": meta.get("dynamic_tools"),
        "bootstrap_messages": [{k: i[k] for k in ("type", "role", "content") if k in i} for i in initial]}
    save(cell / "pre-inference-host.json", host)


def phase(server, opened, reg, cell, checker, deadline, *, compact=False, spent_responses=0):
    verify_pins(reg)
    if reg.get("native_carrier"):
        require(Path(reg["native_carrier"]["workspace"]).resolve() == Path(reg["workspace"]).resolve(),
                "native_carrier_workspace_mismatch")
    from native_execution_binding import verify_execution_binding
    verify_execution_binding(reg, opened)
    tid, path = opened["thread"]["id"], Path(opened["thread"]["path"])
    require(reg.get("accounting_scope") in {None, "fresh_single_turn", "append_only_turn", "fork_append_only_turn"},
            "native_accounting_scope_unregistered")
    fork_accounting = reg.get('accounting_scope') == 'fork_append_only_turn'
    execution_model = reg['model'] if fork_accounting else MODEL
    execution_effort = reg['effort'] if fork_accounting else 'max'
    append_accounting = reg.get("accounting_scope") in {'append_only_turn', 'fork_append_only_turn'}
    prior_response_ids = set()
    if append_accounting:
        from native_turn_accounting import account_turn, admit_resumed_turn
        before_raw = path.read_bytes()
        if fork_accounting:
            from native_fork_phase import fork_baseline, account_admitted_fork_turn
            from native_rollout_snapshot import parse_rollout
            from native_fork_history import observe_fork_bytes
            before_snapshot = parse_rollout(before_raw)
            fork_boundary = fork_baseline(before_raw, reg['fork_history_binding'], thread_id=tid)
            save(cell / 'fork-accounting-start.json', fork_boundary)
        else:
            before_snapshot = admit_resumed_turn(before_raw, thread_id=tid)
        prior_response_ids = {r["payload"]["response_id"] for r in before_snapshot.rows
                              if r["type"] == "token_usage_record"}
        if fork_accounting:
            prior_response_ids.update(fork_boundary['inherited']['response_ids'])
        save(cell / "accounting-start.json", before_snapshot.metadata)
    begin = time.monotonic()
    budget = PhaseBudget.resolve(reg, begin=begin, deadline=deadline,
                                 compact=compact, spent_responses=spent_responses)
    stop = budget.deadline
    output = {"thread_id": tid, "rollout_path": str(path), "completed": False,
              "failure": None, "checks": [], "finals": [], "retry_notices": [], "compaction": compact}
    if budget.explicit:
        output['registered_budget'] = dict(reg['phase_budget'])
    turn_id, completed = None, False
    save(cell / "attempt-started.json", {"method": "thread/compact/start" if compact else "turn/start",
         "model": execution_model, "effort": execution_effort, "utc": datetime.now(timezone.utc).isoformat()})
    try:
        if compact:
            server.call("thread/compact/start", {"threadId": tid})
        else:
            result = server.call("turn/start", {"threadId": tid, "model": execution_model, "effort": execution_effort,
                "input": [{"type": "text", "text": reg["shared_request"]}]})
            turn_id = result["turn"]["id"]
        with (cell / "events.jsonl").open("x", encoding="utf-8") as log:
            while time.monotonic() < stop:
                try:
                    event = server.event(timeout=min(1, max(.01, stop - time.monotonic())))
                except queue.Empty:
                    continue
                log.write(json.dumps(event, ensure_ascii=False) + "\n")
                log.flush()
                method, p = event.get("method"), event.get("params", {})
                if p.get("threadId") not in (None, tid):
                    continue
                if method == "turn/started":
                    turn_id = p["turn"]["id"]
                if method == "item/tool/call":
                    require(not compact and p["tool"] == "RunChecks", "unexpected_dynamic_tool")
                    if p.get("arguments") or len(output["checks"]) >= 3:
                        value, ok = {"status": "denied", "reason": "invalid_arguments_or_check_limit"}, False
                    else:
                        value = checker.run(Path(reg["workspace"]), cell / "checks" / str(len(output["checks"])))
                        output["checks"].append(value)
                        ok = True
                        print(json.dumps({"phase": str(cell), "checks": len(output["checks"]), "groups": value["groups"]}), flush=True)
                    server.send({"id": event["id"], "result": {"contentItems": [
                        {"type": "inputText", "text": json.dumps(value, ensure_ascii=False)}], "success": ok}})
                elif "id" in event and method:
                    raise ValueError("unexpected_interactive_callback:" + method)
                if method == "item/completed":
                    item = p.get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                        output["finals"].append(item)
                if method == "error":
                    output["retry_notices"].append(p)
                    raise ValueError("infrastructure_provider_error_or_retry")
                if method == "turn/completed" and (compact or p["turn"]["id"] == turn_id):
                    output["completed"] = p["turn"]["status"] == "completed"
                    completed = True
                    if not output["completed"]:
                        output["failure"] = "native_turn_" + p["turn"]["status"]
                    break
                if method == "thread/tokenUsage/updated" and (not compact or budget.explicit):
                    live_rows = records(path)
                    if append_accounting:
                        # The budget applies to new responses even when an older
                        # window's receipts are incomplete or no longer present.
                        live_rows = [r for r in live_rows if r["type"] == "token_usage_record"
                                     and r["payload"].get("response_id") not in prior_response_ids]
                    receipts = usage(live_rows, tid)
                    # Explicit compaction produces a compacted record rather
                    # than an agent final. Its single response may finish at
                    # the exact cap; excess cost still fails here or at settle.
                    reason = budget.stop_reason(receipts, final=bool(output['finals']) or compact)
                    if reason:
                        output["failure"] = reason
                        break
            else:
                output["failure"] = "registered_wall_cap"
    except Exception as exc:
        output["failure"] = type(exc).__name__ + ":" + str(exc)
    finally:
        if not completed and turn_id:
            try:
                server.call("turn/interrupt", {"threadId": tid, "turnId": turn_id})
                # Drain completion before reading accounting; interrupted work is never retried.
                drain = time.monotonic() + 8
                while time.monotonic() < drain:
                    try:
                        event = server.event(timeout=.5)
                    except queue.Empty:
                        continue
                    if event.get("method") == "turn/completed":
                        break
            except Exception as exc:
                output["interrupt_error"] = str(exc)
        output["seconds"] = time.monotonic() - begin
        try:
            snapshot = capture_rollout(path, archive=cell / "rollout.jsonl")
            rows = snapshot.rows
            output["rollout_snapshot"] = snapshot.metadata
            output["rollout_sha256"] = snapshot.metadata["sha256"]
            if append_accounting:
                after_raw = (cell / "rollout.jsonl").read_bytes()
                if fork_accounting:
                    proof = account_admitted_fork_turn(before_raw, after_raw, baseline=fork_boundary,
                                                       thread_id=tid, turn_id=turn_id)
                else:
                    proof = account_turn(before_raw, after_raw, thread_id=tid, turn_id=turn_id)
                require(proof["after"]["sha256"] == snapshot.metadata["sha256"],
                        "native_accounting_archive_changed")
                output["turn_accounting"] = proof
                output["receipts"] = proof["receipts"]
                output["usage_completion_evidence"] = {"complete": proof["complete"],
                    "reasons": proof["reasons"], "turn_id": turn_id, "scope": proof["scope"],
                    "rollout_sha256": snapshot.metadata["sha256"]}
            else:
                output["receipts"] = usage(rows, tid, line_numbers=snapshot.line_numbers)
                output["usage_completion_evidence"] = completion_evidence(
                    snapshot, output["receipts"], turn_id=turn_id, compact=compact)
            output["usage_complete"] = (output["usage_completion_evidence"]["complete"]
                                         and not output["retry_notices"] and completed)
            if budget.explicit:
                output['budget_observation'] = budget.observation(output['receipts'])
                # Completion can precede the last token-update notification.
                # Check the archived final receipts too, without dropping cost.
                if not output['failure']:
                    output['failure'] = budget.stop_reason(output['receipts'], final=True)
            if compact and output["completed"]:
                require(len(output["receipts"]["compactor_response_ids"]) == 1, "native_compaction_count_mismatch")
            if fork_accounting:
                final_binding = {**reg['fork_history_binding'], 'child_sha256': snapshot.metadata['sha256']}
                material = observe_fork_bytes(after_raw, final_binding)
                save(cell / 'canonical-state.json', {'items': material['items'],
                    'inherited_history_evidence': material['evidence']})
            else:
                save(cell / "canonical-state.json", {"items": state(rows)})
        except Exception as exc:
            output["usage_complete"] = False
            output["accounting_error"] = str(exc)
            if (cell / "rollout.jsonl").exists():
                output["rollout_sha256"] = file_hash(cell / "rollout.jsonl")
        save(cell / "phase-outcome.json", output)
    print(json.dumps({"phase": str(cell), "completed": output["completed"], "failure": output["failure"],
                      "responses": output.get("receipts", {}).get("response_count"), "seconds": output["seconds"]}), flush=True)
    return output


def ensure_phase(outcome):
    require(outcome.get("usage_complete"), "unknown_usage_stop")
    require(not outcome["failure"] or outcome["failure"] in {"registered_response_cap", "registered_wall_cap"},
            "infrastructure_or_execution_failure_stop:" + str(outcome["failure"]))


def prepare_candidate(area, reg, source):
    from native_candidate_evidence import prepare_candidate as prepare_bound
    return prepare_bound(area, reg, source)


def audit_import(cell, items):
    rows = records(cell / "rollout.jsonl")
    original = [row["payload"] for row in rows if row["type"] == "response_item"]
    result = {**import_evidence(original, items),
              "items_sha256": digest(items), "provider_wire_visibility": "not_available"}
    save(cell / "import-audit.json", result)
    require(result["matched"], "native_import_durable_evidence_missing")


def audit_host(cell):
    rows = records(cell / "rollout.jsonl")
    metas = [r["payload"] for r in rows if r["type"] == "session_meta"]
    contexts = [r["payload"] for r in rows if r["type"] == "turn_context"]
    require(len(metas) == 1 and contexts, "host_runtime_evidence_missing")
    require(all(c["model"] == MODEL and c["effort"] == "max" for c in contexts), "runtime_model_drift")
    value = {"base_instructions_sha256": digest(metas[0]["base_instructions"]),
        "dynamic_tools": metas[0].get("dynamic_tools"), "cli_version": metas[0]["cli_version"],
        "model_provider": metas[0]["model_provider"],
        "turn_configuration": {k: contexts[0].get(k) for k in ("model", "effort", "cwd", "approval_policy", "sandbox_policy")},
        "tool_inventory_scope": "Same native binary, configuration and registered tools; provider wire inventory unavailable."}
    save(cell / "host-audit.json", value)
    return value


def audit_workspace(area, arm, reg, outcome, checker):
    work = Path(reg["workspace"])
    final = manifest(work)
    changes = [p for p, h in reg["initial_manifest"].items() if final.get(p) != h]
    protected = [p for p in changes if p not in TARGETS[:2]]
    # Reuse the last actual check only when its exact full Python manifest still matches.
    pm = python_manifest(work)
    historical_digest = __import__("hashlib").sha256(json.dumps(pm, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    current = [c for c in outcome["checks"] if c["verification"]["source_manifest_sha256"] == historical_digest]
    checked = current[-1] if current else checker.run(work, area / arm / "final-offline-check")
    result = {"groups": checked["groups"], "current_check_run_id": checked["run_id"],
        "final_manifest": final, "changed_existing_files": changes, "protected_changes": protected,
        "new_files": sorted(set(final) - set(reg["initial_manifest"])), "finals": outcome["finals"],
        "completed": outcome["completed"], "failure": outcome["failure"],
        "semantic_report_review": "pending_human_agent_review", "cash": None}
    save(area / arm / "artifact-outcome.json", result)
    require(not protected, "protected_inputs_changed")
    return result


def run(area):
    reg = read(area / "registration.json")
    require(reg.get("paired_admission"), "paired_admission_required_for_new_inference")
    if reg["purpose"] == "carrier_acquisition":
        from run_native_acquisition import run as acquire
        return acquire(area)
    from run_admitted_pair import run as run_admitted
    return run_admitted(area)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--paired-admission", action="store_true")
    parser.add_argument("--purpose", choices=("comparison", "C_qualification", "carrier_acquisition"), default="comparison")
    parser.add_argument("--qualification-receipt", type=Path)
    parser.add_argument("--candidate-selection", type=Path)
    parser.add_argument("--study-workspace", type=Path)
    args = parser.parse_args()
    if args.action == "register":
        register(args.origin.resolve(), args.output.resolve(), args.executable.resolve(),
                 paired_admission=args.paired_admission, purpose=args.purpose,
                 qualification=args.qualification_receipt, candidate_selection=args.candidate_selection,
                 study_workspace=args.study_workspace)
    else:
        run(args.output.resolve())


if __name__ == "__main__":
    main()
