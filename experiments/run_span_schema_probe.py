"""Same actual frontier material; enumerated versus compact output references.

No business repair, restart of a failed study, forced compaction or native B/C.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from native_evidence import digest, file_hash, manifest, read, save
from native_generation_scope import generation_scope
from native_scope_observation import record_scope, request_scope
from native_rollout_snapshot import capture_rollout
from run_frontier_generation import (HERE, WSC, Store, MODEL, SETTINGS, FrontierSpanSelectionGenerator,
    describe, encode, require, verify_pins, run as run_generation)
from run_quote_selection_probe import output_schema
from span_reference_schema import compact_schema


def core_factory(area, mode, task_workspace):
    reg = read(area / "registration.json")
    return WSC(Store(area / mode / "state.db", session_id=reg["source_session_id"], workspace=task_workspace),
               access=lambda *args: True)


def adapter_factory(core, snapshot, reg, fn, mode):
    boundary = reg.get("representation_contrast") == "boundary"
    archive = Path(reg["area"]) / "generation-archive"
    if boundary:
        archive = archive / mode
    return FrontierSpanSelectionGenerator(core, snapshot, reg["previous_view"], fn,
        archive_directory=archive, mode="frontier", boundary_policy=mode if boundary else "fixed")


def prepare(area, source, executable, *, contrast="schema"):
    require(contrast in {"schema", "boundary"}, "span_representation_contrast_invalid")
    require(not area.exists(), "span_schema_study_already_exists")
    seed = read(source / "registration.json")
    original_material = read(source / "frontier/original-material.json")
    continuation = Path("D:/agent-task-runs/wsc-generated-covered-C-20261023-v1/C/continuation")
    snapshot = capture_rollout(continuation / "rollout.jsonl")
    phase = read(continuation / "phase-outcome.json")
    scope = generation_scope(snapshot, phase, area / "workspace")
    require(scope["source_execution"] == seed["execution_scope"]["source_execution"],
            "span_schema_source_execution_changed")
    area.mkdir()
    for directory in ("workspace", "frozen-workspace"):
        (area / directory).mkdir()
    reg = {"purpose": "automatic_selection_generation_only", "study": "span_output_schema_comparison",
        "area": str(area), "workspace": str(area / "workspace"), "origin": str(area), "initial_manifest": {},
        "task_workspace": seed["task_workspace"], "execution_scope": scope,
        "source_session_id": original_material["session_id"], "previous_view": seed["previous_view"],
        "executable": str(executable), "model": MODEL, "effort": "max", "settings": SETTINGS,
        "order": ["enumerated", "reference"], "responses_per_arm": 4, "seconds_per_arm": 180,
        "retries": 0, "orchestration": "retained_generation_group_v1", "admission_warmup_threads": 1,
        "registered_utc": datetime.now(timezone.utc).isoformat(), "cash": None,
        "shared_prior_generation": seed["shared_prior_generation"],
        "shared_prior_continuation": seed["shared_prior_continuation"],
        "source_count": seed["source_count"] + 1, "new_task_execution": False, "native_task_comparison": False,
        "contrast": "Only span_refs output-schema membership enumeration versus string shape; actual material and compiler identical.",
        "acceptance": ["Complete unique native usage including failures and compaction",
            "Same actual bootstrap before either paid arm", "Exact unchanged source material and request",
            "Compiler rejects forged, changed or absent references", "No new semantic error in current task state, evidence values or version applicability"],
        "stop": "No retry or cap extension. Unknown usage/infrastructure failure ends study.",
        "limitations": ["One archived source and fixed order; no long-task or B/C superiority claim",
                       "Output schema is not provider wire evidence; real metered receipts determine cost",
                       "Prior excerpt parent expansion has zero avoidable parents in this source"]}
    reg["representation_contrast"] = contrast
    if contrast == "boundary":
        reg.update(study="span_boundary_comparison", order=["fixed", "word"],
            contrast="Same source text, selection and enumerated schema structure; bounded fixed versus lexical partitions and their content-bound references.")
        reg["acceptance"][2] = "Same original material and source order; all public characters retained once; source archive bytes identical"
    requests, schemas, preparations = {}, {}, {}
    for mode in reg["order"]:
        cell = area / mode
        cell.mkdir()
        with sqlite3.connect((source / "base.db").as_uri() + "?mode=ro", uri=True) as src, \
             sqlite3.connect(cell / "state.db") as dst:
            src.backup(dst)
        core = WSC(Store(cell / "state.db", session_id=reg["source_session_id"], workspace=reg["task_workspace"]),
                   access=lambda *args: True)
        captured = core.capture()
        material = {**core.material(captured), "selection_facts": describe(captured.events, 262144)}
        require(material == original_material, "span_schema_frozen_material_changed")
        scope_binding = record_scope(core, snapshot, phase, area / "workspace", observed_at=reg["registered_utc"])
        if "scope_observation" in reg:
            require(reg["scope_observation"] == scope_binding, "span_probe_scope_observations_differ")
        reg["scope_observation"] = scope_binding
        captured = core.capture()
        material = {**core.material(captured), "selection_facts": describe(captured.events, 262144)}
        generator = adapter_factory(core, captured, reg, None, mode)
        offered = generator.offer(material)
        request = {"operation": "working_state_selection", "task_request": "继续处理当前任务状态和后续用户要求。",
            "execution_scope": request_scope(material, scope_binding, scope),
            "source_status": "Archived consecutive task observations; selection generation only, no task execution.",
            "output_contract": {"source_ids": "Complete original records selected by catalog alias, including cold records.",
                "understanding_refs": "Selected existing exact model-record revisions.",
                "new_understandings": "Model-authored current interpretations with provenance; existing identity uses its expected_revision.",
                "span_refs": "Exact content-bound references carried by inline spans or archived span files."},
            "material": offered}
        schema = output_schema(generator.full_material, "span")
        fields = schema["properties"]["new_understandings"]["items"]
        fields["properties"].update(id={"type": ["string", "null"]}, expected_revision={"type": ["integer", "null"]})
        fields["required"].extend(["id", "expected_revision"])
        if mode == "reference":
            schema = compact_schema(schema)
        save(cell / "request.json", request)
        save(cell / "schema.json", schema)
        save(cell / "original-material.json", material)
        save(cell / "preparation.json", generator.preparation)
        requests[mode], schemas[mode], preparations[mode] = request, schema, generator.preparation
    if contrast == "schema":
        require(requests["enumerated"] == requests["reference"], "span_schema_requests_differ")
        require(compact_schema(schemas["enumerated"]) == schemas["reference"], "span_schema_other_fields_differ")
    else:
        from span_boundary_comparison import verify_contrast
        save(area / "partition-proof.json", verify_contrast(requests, schemas))
    pins = [executable, source / "registration.json", source / "base.db", source / "frontier/original-material.json",
            continuation / "rollout.jsonl", continuation / "phase-outcome.json"]
    pins += [p for folder in ("src", "experiments", "tests") for p in (HERE.parent / folder).rglob("*.py")]
    pins += [p for mode in reg["order"] for p in (area / mode).glob("*.json")]
    pins += [p for p in (area / "generation-archive").rglob("*") if p.is_file()]
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        pins.append(config)
    reg["pins"] = {str(p.resolve()): file_hash(p) for p in pins}
    reg["request_sha256"] = {mode: digest(request) for mode, request in requests.items()}
    reg["schema_bytes"] = {mode: len(encode(value).encode("utf-8")) for mode, value in schemas.items()}
    save(area / "registration.json", reg)
    verify_pins(reg)
    print({"registered": str(area), "schema_bytes": reg["schema_bytes"], "model_calls": 0}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("area", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--contrast", choices=("schema", "boundary"), default="schema")
    args = parser.parse_args()
    if args.action == "prepare":
        require(args.source is not None and args.executable is not None, "span_schema_prepare_arguments_missing")
        prepare(args.area.resolve(), args.source.resolve(), args.executable.resolve(), contrast=args.contrast)
    else:
        run_generation(args.area.resolve(), adapter_factory=adapter_factory, core_factory=core_factory)
