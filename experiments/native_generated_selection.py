"""Admit an unchanged model-generated selection and its actual paid receipt."""
from dataclasses import asdict

from native_evidence import read, file_hash, usage
from native_rollout_snapshot import capture_rollout
from native_usage_boundary import completion_evidence
from native_generation_binding import verify_turn
from wsc.contracts import encode, require
from wsc.projection import public_material
from wsc.span_selection import compile_spans


def verify(plan, batch, selection):
    binding = plan.get("generated_selection")
    if binding is None:
        return None
    require(binding.get("format") == "bound_spans_v1" and binding.get("max_chars") == 1024,
            "generated_selection_format_unknown")
    refs = binding.get("evidence", {})
    require(set(refs) == {"material", "draft", "phase", "rollout"}, "generated_selection_evidence_missing")
    for ref in refs.values():
        require(set(ref) == {"path", "sha256"} and file_hash(ref["path"]) == ref["sha256"],
                "generated_selection_evidence_changed")
    material, draft, phase = [read(refs[k]["path"]) for k in ("material", "draft", "phase")]
    prefix = [{**asdict(event), "seq": i + 1} for i, event in enumerate(batch)]
    expected = public_material(prefix, [])
    require(material["events"] == expected["events"] and material["understandings"] == []
            and material["source_boundary"] == len(batch), "generated_selection_source_changed")
    compiled = compile_spans(material, draft, max_chars=binding["max_chars"])
    require(encode(asdict(compiled)) == encode(asdict(selection)), "generated_selection_manually_changed")
    require(phase["completed"] and phase["usage_complete"] and not phase["failure"]
            and len(phase["finals"]) == 1, "generated_selection_turn_incomplete")
    import json
    require(json.loads(phase["finals"][0]["text"]) == draft, "generated_selection_not_final_output")
    snapshot = capture_rollout(refs["rollout"]["path"])
    receipts = usage(snapshot.rows, phase["thread_id"], line_numbers=snapshot.line_numbers)
    proof = completion_evidence(snapshot, receipts,
        turn_id=phase["usage_completion_evidence"]["turn_id"], compact=False)
    require(proof["complete"] and receipts == phase["receipts"]
            and snapshot.metadata["sha256"] == phase["rollout_sha256"], "generated_selection_usage_unproven")
    turn_binding = verify_turn(snapshot, phase, material, prefix, max_chars=binding["max_chars"])
    return {"generation_thread": phase["thread_id"], "receipts": receipts,
            "new_generation_calls_during_preparation": 0,
            "selection_replayed_exactly": True, "turn_binding": turn_binding, "cash": None}
