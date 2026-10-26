"""Build one current-reference addendum around an unchanged native checkpoint."""
import time

from native_evidence import digest, file_hash, save
from native_candidate_evidence import selected_material
from native_carrier_source import load_carrier
from wsc import WSC, Store, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.native_carrier import NativeCarrierCheckpointAdapter
from wsc.contracts import require
from wsc.publication import check_evidence


def prepare_candidate(area, reg, source):
    cell = area / "C"
    cell.mkdir(exist_ok=False)
    began = time.monotonic()
    reference = reg["candidate_selection"]
    require(file_hash(reference["path"]) == reference["sha256"], "candidate_selection_changed")
    plan, batch, selection, resolved = selected_material(reference["path"], source)
    require(len(selection.excerpts) == 1 and selection.excerpts[0].current_resource is not None and
            not selection.new_understandings and not selection.understanding_refs and
            not selection.source_ids and not selection.clues, "carrier_single_reference_selection_required")
    carrier = load_carrier(plan, source)
    require(carrier["carrier_sha256"] == reg["native_carrier"]["carrier_sha256"], "registered_carrier_changed")
    adapter = NativeCarrierCheckpointAdapter(carrier["item"], source_count=len(batch),
                                              source_digest=digest(source["items"]), workspace=carrier["workspace"])
    checkpoint_event = CodexCheckpointAdapter().import_items([carrier["item"]],
        thread_id="compacted-state:" + carrier["thread_id"], start_ordinal=carrier["ordinal"],
        observed_at=[carrier["observed_at"]])
    core = WSC(Store(cell / "state.db", session_id=area.name + ":C", workspace=reg["workspace"]),
               access=lambda *args: True)
    core.ingest(batch + checkpoint_event)
    core.presented("archived-diagnostic-result-delivery", tuple(e.id for e in batch if e.kind == "result"),
                   receiver="historical_native_diagnostic:" + source["thread_id"])
    view = core.prepare(core.capture(), selection, producer=plan["producer"], limits=Limits(max_view_bytes=262144))
    operation = core.stage(view, directory=cell / "exports", adapter=adapter)
    package = core.package(operation)
    check_evidence(core, package)
    controls = [i for i in source["items"] if i.get("role") in {"user", "system", "developer"}]
    require(package["items"][:len(controls)] == controls and
            package["items"][len(controls)] == carrier["item"], "carrier_or_controls_changed")
    require(len(package["items"]) == len(controls) + 2, "carrier_addendum_shape_changed")
    text = package["items"][-1]["content"][0]["text"]
    require(resolved[0]["text"] in text, "carrier_addendum_observation_missing")
    require(len(text) <= plan["max_addendum_chars"], "carrier_addendum_budget_exhausted")
    bindings = package.get("current_reference_bindings", [])
    require(len(bindings) == 1 and bindings[0]["status"] == "unique_content_match",
            "candidate_reference_relocation_unresolved")
    save(cell / "selection-audit.json", {"selection_sha256": reference["sha256"],
        "source_items_sha256": digest(source["items"]), "presentation": plan["presentation"],
        "semantic_selection": "explicit_single_reference_not_automatic", "producer": plan["producer"],
        "carrier_sha256": carrier["carrier_sha256"], "carrier_protocol_value_unchanged": True,
        "observations": [{k: e[k] for k in ("key", "source_id", "text_sha256", "observed_at")} for e in resolved],
        "current_reference_bindings": bindings, "exported_observations": package["excerpt_evidence"],
        "export_integrity_verified": True, "source_times_from_archived_rollout": True,
        "addendum_chars": len(text), "max_addendum_chars": plan["max_addendum_chars"]})
    save(cell / "preparation.json", {"seconds": time.monotonic() - began, "operation": operation,
        "package_digest": package["package_digest"], "wsc_state": "ready", "model_generation_calls": 0,
        "workspace": reg["workspace"], "selection_sha256": reference["sha256"],
        "shared_native_compaction_acquisition_receipts": carrier["shared_acquisition_receipts"],
        "selection_authoring_cost": "parent_agent_usage_not_available_not_zero",
        "cost_policy": "Native checkpoint acquisition is shared and attributed equally to B and C; this preparation does not regenerate it."})
    return package["items"]
