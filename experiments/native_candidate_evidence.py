"""Registered model-selected evidence, checked before any native inference."""
from dataclasses import asdict
import json
import time

from native_evidence import digest, file_hash, read, records, save
from wsc import WSC, Store, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import require
from wsc.excerpts import resolve
from wsc.generation import selection_from_json


def selected_material(plan_path, source):
    plan = read(plan_path)
    require(plan["source_items_sha256"] == digest(source["items"]), "selection_source_boundary_changed")
    # These are archived native event times, never the time of this replay.
    require(file_hash(source["rollout_path"]) == source["rollout_sha256"], "source_rollout_changed")
    history = [r for r in records(source["rollout_path"]) if r["type"] == "response_item"]
    require([r["payload"] for r in history] == source["items"], "source_rollout_boundary_changed")
    batch = CodexCheckpointAdapter().import_items(source["items"], thread_id=source["thread_id"],
        observed_at=[r.get("timestamp") for r in history])
    selection = selection_from_json(plan["selection"])
    resolved = resolve(selection.excerpts, {e.id: asdict(e) for e in batch}, bind_live=False)
    require(resolved and (selection.new_understandings or
            plan.get("presentation") == "native_carrier_facts_v1"), "evidence_selection_empty")
    keys = {item["key"] for item in resolved}
    require(set(plan["required_observations"]) <= keys, "required_observation_missing")
    from native_generated_selection import verify
    generated = verify(plan, batch, selection)
    if generated is not None:
        plan = {**plan, "verified_generation": generated}
    return plan, batch, selection, resolved


def prepare_candidate(area, reg, source):
    if read(reg["candidate_selection"]["path"]).get("presentation") == "native_carrier_facts_v1":
        from native_carrier_candidate import prepare_candidate as prepare_carrier
        return prepare_carrier(area, reg, source)
    cell = area / "C"
    cell.mkdir(exist_ok=False)
    began = time.monotonic()
    reference = reg["candidate_selection"]
    require(file_hash(reference["path"]) == reference["sha256"], "candidate_selection_changed")
    plan, batch, selection, resolved = selected_material(reference["path"], source)
    core = WSC(Store(cell / "state.db", session_id=area.name + ":C", workspace=reg["workspace"]),
               access=lambda *args: True)
    core.ingest(batch)
    core.presented("archived-diagnostic-result-delivery", tuple(e.id for e in batch if e.kind == "result"),
                   receiver="historical_native_diagnostic:" + source["thread_id"])
    view = core.prepare(core.capture(), selection, producer=plan["producer"],
                        limits=Limits(max_view_bytes=262144))
    presentation = plan.get("presentation", "canonical_json_v1")
    require(presentation in {"canonical_json_v1", "factual_view_v1", "covered_json_v1"}, "candidate_presentation_unknown")
    adapter = CodexCheckpointAdapter()
    if presentation == "covered_json_v1":
        from wsc.adapters.covered_codex import CoveredCodexCheckpointAdapter
        adapter = CoveredCodexCheckpointAdapter()
    if presentation == "factual_view_v1":
        from wsc.adapters.factual_codex import FactualCodexCheckpointAdapter
        current = json.loads(reg["common_workspace_fact"]["content"][0]["text"])
        adapter = FactualCodexCheckpointAdapter(execution_facts={key: current[key] for key in
            ("current_workspace", "historical_workspace", "current_file_mapping")})
    operation = core.stage(view, directory=cell / "exports", adapter=adapter)
    package = core.package(operation)
    from wsc.publication import check_evidence
    check_evidence(core, package)
    if presentation == "factual_view_v1":
        from native_presentation_admission import presentation_evidence
        save(cell / "presentation-audit.json", presentation_evidence(core, view, package, resolved))
    bindings = package.get("current_reference_bindings", [])
    require(all(b["status"] == "unique_content_match" for b in bindings),
            "candidate_reference_relocation_unresolved")
    save(cell / "selection-audit.json", {"selection_sha256": reference["sha256"],
        "source_items_sha256": digest(source["items"]), "producer": plan["producer"],
        "observations": [{k: item[k] for k in ("key", "source_id", "text_sha256", "observed_at")}
                         for item in resolved],
        "exported_observations": package["excerpt_evidence"],
        "source_times_from_archived_rollout": True, "export_integrity_verified": True,
        "current_reference_bindings": bindings,
        "semantic_selection": "native_generated_replayed_exactly" if plan.get("verified_generation") else "explicit_model_authored_not_automatic",
        "generation_evidence": plan.get("verified_generation"), "presentation": presentation,
        "current_applicability": "model_judgment_using_common_workspace_binding"})
    save(cell / "preparation.json", {"seconds": time.monotonic()-began, "operation": operation,
        "package_digest": package["package_digest"], "wsc_state": "ready", "model_generation_calls": 0,
        "workspace": reg["workspace"], "historical_diagnostic_cost_attributed": True,
        "selection_authoring_cost": plan.get("verified_generation") or "parent_agent_usage_not_available_not_zero",
        "selection_sha256": reference["sha256"], "exact_observations": len(resolved)})
    return package["items"]
