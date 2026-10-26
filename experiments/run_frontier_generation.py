"""One registered full/frontier generation comparison on a real later task stage.

No task repair, native compaction comparison, automatic retry or host installation.
"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from wsc import WSC, Store, Selection, Understanding, Usage, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.covered_codex import CoveredCodexCheckpointAdapter
from wsc.contracts import encode, require
from wsc.generation_frontier import FrontierSpanSelectionGenerator
from wsc.quote_selection import SelectionDraft
from wsc.selection_facts import describe
from wsc.publication import check_evidence
from native_candidate_evidence import selected_material
from native_evidence import read, save, file_hash, digest, manifest, usage
from native_rollout_snapshot import capture_rollout
from native_usage_boundary import completion_evidence
from native_generation_binding import verify_transcript
from native_generation_admission import admit
from native_generation_scope import generation_scope
from native_scope_observation import record_scope, request_scope
from native_thread_archive import archive_threads
from native_rpc import NativeRPC
from run_native_pair import MODEL, SETTINGS, initialize, phase, audit_host, verify_pins
from run_quote_selection_probe import SchemaServer, output_schema


def open_core(area, mode, task_workspace):
    return WSC(Store(area / mode / "state.db", session_id=area.name, workspace=task_workspace),
               access=lambda *args: True)


def adapter(core, snapshot, reg, fn, mode):
    return FrontierSpanSelectionGenerator(core, snapshot, reg["previous_view"], fn,
        archive_directory=Path(reg["area"]) / "generation-archive", mode=mode)


def prepare(area, executable):
    area.mkdir(parents=True, exist_ok=False)
    (area / "workspace").mkdir()
    old = Path("D:/agent-task-runs/wsc-span-selection-20261023-v1")
    continuation = Path("D:/agent-task-runs/wsc-generated-covered-C-20261023-v1/C/continuation")
    source_path = Path("D:/agent-task-runs/native-wsc-compaction-pair-c7e1d8ba3f/common-native-source.json")
    selection_path = HERE.parent / "validation/observation-coverage-20261023/generated-selection.json"
    plan, original, selected, _ = selected_material(selection_path, read(source_path))
    phase_result = read(continuation / "phase-outcome.json")
    snapshot = capture_rollout(continuation / "rollout.jsonl")
    receipts = usage(snapshot.rows, phase_result["thread_id"], line_numbers=snapshot.line_numbers)
    turn = phase_result["usage_completion_evidence"]["turn_id"]
    require(completion_evidence(snapshot, receipts, turn_id=turn, compact=False)["complete"]
            and receipts == phase_result["receipts"] and snapshot.metadata["sha256"] == phase_result["rollout_sha256"],
            "frontier_source_continuation_unproven")
    starts = [i for i, r in enumerate(snapshot.rows) if r["type"] == "event_msg"
              and r["payload"].get("type") == "task_started" and r["payload"].get("turn_id") == turn]
    require(len(starts) == 1, "frontier_source_turn_ambiguous")
    start = starts[0]
    delta = [r for r in snapshot.rows[start:] if r["type"] == "response_item"]
    new_events = CodexCheckpointAdapter().import_items([r["payload"] for r in delta],
        thread_id=phase_result["thread_id"], start_ordinal=sum(r["type"] == "response_item" for r in snapshot.rows[:start]),
        observed_at=[r.get("timestamp") for r in delta])
    scope = generation_scope(snapshot, phase_result, area / "workspace")
    task_workspace = scope["source_execution"]["workspace"]
    core = WSC(Store(area / "base.db", session_id=area.name, workspace=task_workspace),
               access=lambda *args: True)
    core.ingest(original)
    core.presented("historical-native-results", tuple(e.id for e in original if e.kind == "result"),
                   receiver="archived-native-diagnostic")
    package = read(old / "package.json")
    memories = read(package["understanding_index"])
    require(digest(memories) == package["understanding_index_sha256"], "frontier_previous_memories_changed")
    for memory in memories:
        require(memory["revision"] == 1 and memory["previous"] is None, "frontier_fixture_revision_unknown")
        record = core.remember(Understanding(memory["text"], memory["kind"], tuple(memory["sources"]),
            scope=memory["scope"], id=memory["id"]), producer=memory["producer"])
        require(encode(record) == encode(memory), "frontier_previous_memory_replay_changed")
    previous = core.prepare(core.capture(), replace(selected, new_understandings=(),
        understanding_refs=tuple(r["ref"] for r in memories)), producer=plan["producer"], limits=Limits(max_view_bytes=262144))
    core.ingest(new_events)
    core.presented("later-native-results", tuple(e.id for e in new_events if e.kind == "result"),
                   receiver="archived-native-turn:" + turn)
    registered_at = datetime.now(timezone.utc).isoformat()
    scope_binding = record_scope(core, snapshot, phase_result, area / "workspace", observed_at=registered_at)
    reg = {"purpose": "automatic_selection_generation_only", "area": str(area), "workspace": str(area / "workspace"), "origin": str(area), "initial_manifest": {},
        "task_workspace": task_workspace, "execution_scope": scope,
        "model": MODEL, "effort": "max", "executable": str(executable), "previous_view": previous,
        "order": ["full", "frontier"], "responses_per_arm": 4, "seconds_per_arm": 180, "retries": 0,
        "source_count": len(original) + len(new_events) + 1, "source_turn": turn,
        "scope_observation": scope_binding,
        "shared_prior_generation": plan["verified_generation"]["receipts"],
        "shared_prior_continuation": receipts, "new_task_execution": False, "native_task_comparison": False,
        "registered_utc": registered_at, "cash": None}
    reg.update(orchestration="retained_generation_group_v1", admission_warmup_threads=1)
    offered = {}
    for mode in reg["order"]:
        (area / mode).mkdir()
        with core.store.connect() as source, sqlite3.connect(area / mode / "state.db") as dest:
            source.backup(dest)
        fork = open_core(area, mode, reg["task_workspace"])
        captured = fork.capture()
        generator = adapter(fork, captured, reg, None, mode)
        material = {**fork.material(captured), "selection_facts": describe(captured.events, 262144)}
        offered[mode] = generator.offer(material)
        save(area / mode / "preparation.json", generator.preparation)
        save(area / mode / "original-material.json", material)
        request = {"operation": "working_state_selection", "task_request": "继续处理当前任务状态和后续用户要求。",
            "execution_scope": request_scope(material, scope_binding, scope),
            "source_status": "Archived consecutive task observations, including a later native turn; selection generation only, no task execution.",
            "output_contract": {"source_ids": "Selected original records by catalog alias, including cold records.",
                "understanding_refs": "Selected existing exact model-record revisions.",
                "new_understandings": "Revisable model understanding with exact sources; id and expected_revision identify a revision, null denotes a new record.",
                "clues": "Model-selected discovery text with source aliases.",
                "span_refs": "Exact selected catalog span identities; original text is compiled outside the model."},
            "material": offered[mode]}
        save(area / mode / "request.json", request)
        schema = output_schema(generator.full_material, "span")
        fields = schema["properties"]["new_understandings"]["items"]
        fields["properties"].update(id={"type": ["string", "null"]}, expected_revision={"type": ["integer", "null"]})
        fields["required"].extend(["id", "expected_revision"])
        save(area / mode / "schema.json", schema)
    require({k: v for k, v in offered["full"].items() if k != "events"} ==
            {k: v for k, v in offered["frontier"].items() if k != "events"}, "frontier_uncontrolled_material_difference")
    require(read(area / "full/schema.json") == read(area / "frontier/schema.json"), "frontier_schema_difference")
    pins = [executable, source_path, selection_path, continuation / "rollout.jsonl", continuation / "phase-outcome.json",
            old / "package.json", Path(package["understanding_index"]), *HERE.glob("*.py"), *(HERE.parent / "src").rglob("*.py")]
    pins.extend(p for mode in reg["order"] for p in (area / mode).glob("*.json"))
    pins.extend(p for p in (area / "generation-archive").rglob("*") if p.is_file())
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        pins.append(config)
    reg["pins"] = {str(p.resolve()): file_hash(p) for p in pins}
    save(area / "registration.json", reg)
    print(json.dumps({"registered": str(area), "preparation": {m: read(area / m / "preparation.json") for m in reg["order"]}}), flush=True)


def run(area, *, adapter_factory=adapter, core_factory=open_core):
    reg = read(area / "registration.json")
    verify_pins(reg)
    save(area / "started.json", {"utc": datetime.now(timezone.utc).isoformat(), "retry": False})
    opened, results = {}, {}
    with NativeRPC(reg["executable"], cwd=reg["workspace"], stderr_path=area / "stderr.txt", settings=SETTINGS) as server:
        save(area / "initialize.json", initialize(server))
        save(area / "quota-before.json", server.call("account/rateLimits/read", {}))
        try:
            gate, observations = admit(server, reg, area, opened)
            for mode in reg["order"]:
                cell = area / mode
                (cell / "generation").mkdir()
                core = core_factory(area, mode, reg["task_workspace"])
                outcome = None
                def generate(material):
                    nonlocal outcome
                    request = read(cell / "request.json")
                    require(request["material"] == material, "frontier_registered_material_changed")
                    value = opened[mode]
                    save(cell / "thread-start.json", value)
                    require(value["model"] == MODEL and value.get("reasoningEffort") == "max"
                            and value["sandbox"]["type"] == "readOnly", "frontier_native_configuration_changed")
                    outcome = gate.execute(mode, observations(), lambda: phase(SchemaServer(server, read(cell / "schema.json")), value,
                        {**reg, "shared_request": encode(request)}, cell / "generation", None,
                        time.monotonic() + reg["seconds_per_arm"], spent_responses=10-reg["responses_per_arm"]))
                    known = Usage()
                    if outcome.get("usage_complete"):
                        u = outcome["receipts"]["all_usage"]
                        known = Usage(u["input_tokens"]-u["cached_input_tokens"], u["cached_input_tokens"], u["output_tokens"])
                    try:
                        require(outcome.get("usage_complete") and outcome["completed"] and not outcome["failure"]
                                and len(outcome["finals"]) == 1, "frontier_generation_incomplete")
                        audit_host(cell / "generation")
                        binding, actual_request = verify_transcript(
                            capture_rollout(cell / "generation/rollout.jsonl"), outcome)
                        require(actual_request == request, "frontier_actual_request_changed")
                        save(cell / "generation-binding.json", binding)
                        draft = json.loads(outcome["finals"][0]["text"])
                        save(cell / "model-draft.json", draft)
                        verify_pins(reg)
                        require(manifest(reg["workspace"]) == {}, "frontier_generation_workspace_changed")
                        return SelectionDraft(draft, known)
                    except Exception as exc:
                        exc.usage = known
                        raise
                generator = adapter_factory(core, core.capture(), reg, generate, mode)
                result = {"status": "not_started", "semantic_review": "pending", "cash": None}
                try:
                    view = core.generate(core.capture(), generator, producer="native_model:" + MODEL,
                        limits=Limits(max_material_bytes=524288, max_view_bytes=262144), include_selection_facts=True)
                    operation = core.stage(view, directory=cell / "exports", adapter=CoveredCodexCheckpointAdapter())
                    package = core.package(operation)
                    check_evidence(core, package)
                    save(cell / "package.json", package)
                    result.update(status="generated_compiled_exported", view=view, operation=operation,
                                  rendered_bytes=len(encode(package["items"]).encode("utf-8")))
                except Exception as exc:
                    result.update(status="failed_preserved", error=type(exc).__name__ + ":" + str(exc))
                result["usage"] = core.status()["usage"]
                save(cell / "result.json", result)
                results[mode] = result
                print(json.dumps({"arm": mode, "status": result["status"], "error": result.get("error")}), flush=True)
                if outcome is None or not outcome.get("usage_complete") or outcome.get("retry_notices"):
                    break
        finally:
            save(area / "thread-archive.json", archive_threads(area, opened))
            save(area / "result.json", {"arms": results, "state": "executed_review_pending", "model_calls_not_retried": True})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("prepare", "run"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--executable", type=Path)
    a = p.parse_args()
    if a.action == "prepare":
        prepare(a.output.resolve(), a.executable.resolve())
    else:
        run(a.output.resolve())
