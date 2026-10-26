"""Freeze pre-repair materials for a bounded benefit pilot; no inference.

This is research preparation, not the host installation adapter. A live runner
must still bind an isolated workspace, pin its actual host configuration and
provide model/usage receipts. No legacy WSC module is imported.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Limits, Selection, Understanding
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import digest, encode, require


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    origin, output = args.origin.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_path = origin / "common-native-source.json"
    source = read(source_path)
    items = source["items"]
    prior = read(origin / "registration-v2.json")
    native = read(origin / "native-v2/native-restoration.json")
    diagnostic = read(origin / "diagnostic/phase-outcome.json")
    compaction = read(origin / "native/compaction/phase-outcome.json")
    require(diagnostic["completed"] and diagnostic["failure"] is None,
            "diagnostic_checkpoint_incomplete")
    require(compaction["completed"] and compaction["failure"] is None,
            "native_checkpoint_incomplete")
    require(items[-1].get("phase") == "final_answer", "checkpoint_not_final_reply")
    common_controls = [i for i in items if i.get("role") in {"system", "developer", "user"}]
    native_users = [i for i in native if i.get("role") == "user"]
    original_users = [i for i in common_controls if i.get("role") == "user"]
    public_message = lambda i: {k: i.get(k) for k in ("type", "role", "content")}
    require([public_message(i) for i in native_users] == [public_message(i) for i in original_users],
            "native_user_history_mismatch")
    require(not any(i.get("role") in {"system", "developer"} for i in native),
            "native_control_scope_unknown")
    # B receives exactly the same original developer prefix as current WSC.
    # The opaque native compactor output itself remains unchanged. This is a
    # matched-recovery material pilot, not untouched native continuous arm A.
    # The native compactor regenerated a transport ID on an otherwise identical
    # user message. Normalize ONLY those envelope identities to the same original
    # messages used by C, after exact role/type/content equality above.
    opaque = [i for i in native if i.get("type") == "compaction"]
    require(len(native) == len(native_users) + len(opaque) and len(opaque) == 1,
            "native_restoration_shape_unknown")
    baseline = common_controls + opaque
    source_manifest = {p.relative_to(origin / "frozen-workspace").as_posix(): sha256(p.read_bytes()).hexdigest()
                       for p in (origin / "frozen-workspace").rglob("*.py") if "__pycache__" not in p.parts}
    require(source_manifest == prior["initial_python_manifest"], "frozen_workspace_changed")
    core = WSC(Store(output / "state.db", session_id="benefit-preparation:" + digest(items),
                     workspace=str(output / "provisional-workspace")), access=lambda *args: True)
    adapter = CodexCheckpointAdapter()
    batch = adapter.import_items(items, thread_id=source["thread_id"])
    core.ingest(batch)
    core.presented("offline-preparation", tuple(e.id for e in batch if e.kind == "result"),
                   receiver="offline_preparation_not_live_model")
    last = batch[-1]
    view = core.prepare(core.capture(), Selection(new_understandings=(Understanding(
        last.text, "existing_diagnostic_reply", (last.id,),
        scope={"source_ordinal": len(batch)-1, "current_applicability": "unverified"}),)),
        producer="explicit_replay_of_pre_repair_reply", limits=Limits(max_view_bytes=262144))
    operation = core.stage(view, directory=output / "exports", adapter=adapter)
    candidate = core.package(operation)["items"]
    require([i for i in baseline if i.get("role") in {"user", "system", "developer"}] == common_controls,
            "baseline_control_order_mismatch")
    require([i for i in candidate if i.get("role") in {"user", "system", "developer"}] == common_controls,
            "candidate_control_order_mismatch")
    save(output / "B-native-recovery.json", baseline)
    save(output / "C-wsc-recovery.json", candidate)
    pins = {str(p): sha256(p.read_bytes()).hexdigest() for p in (
        source_path, origin / "registration-v2.json", origin / "native-v2/native-restoration.json",
        origin / "diagnostic/phase-outcome.json", origin / "native/compaction/phase-outcome.json")}
    code = Path(__file__).resolve().parents[1] / "src"
    pins.update({str(p): sha256(p.read_bytes()).hexdigest() for p in code.rglob("*.py")})
    report = {
        "status": "materials_prepared_live_execution_blocked",
        "question": "Does reusing the actual pre-repair diagnosis through independent WSC reduce continuation errors and full cost versus native checkpoint recovery?",
        "evidence_level": "offline_preflight_only", "source_items": len(items),
        "understanding_ordinal": len(items)-1, "understanding_characters": len(last.text),
        "completed_repair_material_used_as_input": False,
        "common_original_controls_equal": True,
        "native_user_transport_normalization": [
            {"ordinal": index, "original_sha256": digest(original), "restored_sha256": digest(restored),
             "role_type_content_equal": True,
             "changed_envelope_fields": sorted(k for k in set(original) | set(restored)
                                                if original.get(k) != restored.get(k))}
            for index, (original, restored) in enumerate(zip(original_users, native_users))],
        "frozen_python_files_match_registered_baseline": len(source_manifest),
        "source_pins": pins,
        "shared_diagnostic_usage": diagnostic["receipts"]["all_usage"],
        "native_compaction_usage": compaction["receipts"]["compaction_usage"],
        "new_wsc_generation_calls": 0, "new_live_model_calls": 0,
        "automatic_semantic_selection_tested": False,
        "material_selection": "explicit_existing_diagnosis_reuse_research_choice",
        "shared_current_task_request": prior["continuation_request"],
        "suggested_initial_caps": {"pairs": 1, "responses_per_arm": 10,
                                  "wall_seconds_per_arm": 480, "check_invocations_per_arm": 3},
        "frozen_acceptance": ["Current-artifact 13 business and 5 owned regression cases",
                              "Original tests, pairing.py and unrelated inputs unchanged",
                              "Actual final report matches observed scope and results",
                              "All attempts: uncached/cached input, output, retries, retrieval and elapsed time"],
        "stop_conditions": ["Input/control/source drift", "Unknown execution or usage outcome",
                            "Registered budget exhausted; no unregistered extension"],
        "cost_rule": "Report full attributed costs and conditional continuation separately; unknown prices are not zero; no claim from byte count",
        "verdict": None,
        "live_admission_pending": ["Callable native execution entrypoint",
                                   "Isolated same-source workspace and absolute-path handling",
                                   "Same model, tools, system context and recovery boundary",
                                   "Actual installed-context and complete usage receipts"],
        "codex_on_current_path": shutil.which("codex"),
        "limitations": ["No fresh native continuous arm A",
                        "Single selected repair cannot establish general or multi-compaction benefit",
                        "Original developer prefix reattached identically in both B and C",
                        "Prepared WSC package has provisional workspace binding; regenerate for live workspace",
                        "Offline presentation receipt does not certify native model consumption"]}
    save(output / "preflight.json", report)
    print(encode({k: report[k] for k in ("status", "source_items", "understanding_characters",
                "common_original_controls_equal", "frozen_python_files_match_registered_baseline",
                "new_live_model_calls", "codex_on_current_path", "verdict")}))


if __name__ == "__main__":
    main()
