"""Verify a real pre-repair native compaction before reusing its opaque value."""
from pathlib import Path

from native_evidence import digest, file_hash, read, state, usage
from native_rollout_snapshot import capture_rollout
from native_usage_boundary import completion_evidence
from wsc.contracts import require


def load_carrier(plan, source):
    reference = plan["native_carrier"]
    proof_path = Path(reference["proof"])
    require(file_hash(proof_path) == reference["proof_sha256"], "carrier_proof_changed")
    proof = read(proof_path)
    directory = Path(reference["directory"]).resolve()
    registration = directory.parent.parent / "registration.json"
    required = [registration, *(directory / name for name in
        ("installed-items.json", "rollout.jsonl", "phase-outcome.json", "canonical-state.json", "import-audit.json"))]
    for path in required:
        require(str(path) in proof["pins"], "carrier_source_pin_missing")
    for path, expected in proof["pins"].items():
        require(file_hash(path) == expected, "carrier_source_changed:" + path)
    previous = read(registration)
    inputs = read(directory / "installed-items.json")
    require(inputs == source["items"] + [previous["common_workspace_fact"]], "carrier_input_not_common_pre_repair_source")
    require(proof["source_items_sha256"] == digest(source["items"]), "carrier_source_boundary_changed")
    require(read(directory / "import-audit.json")["matched"], "carrier_original_import_unverified")
    snapshot = capture_rollout(directory / "rollout.jsonl")
    outcome = read(directory / "phase-outcome.json")
    require(outcome["completed"] and outcome["usage_complete"] and not outcome["failure"], "carrier_phase_not_complete")
    require(snapshot.metadata["sha256"] == outcome["rollout_sha256"], "carrier_rollout_changed")
    receipts = usage(snapshot.rows, outcome["thread_id"], line_numbers=snapshot.line_numbers)
    require(receipts == outcome["receipts"], "carrier_usage_changed")
    usage_rows = [r["payload"] for r in snapshot.rows if r["type"] == "token_usage_record"]
    require(len(usage_rows) == 1, "carrier_response_count_mismatch")
    complete = completion_evidence(snapshot, receipts, turn_id=usage_rows[0]["turn_id"], compact=True)
    require(complete["complete"], "carrier_durable_completion_unverified")
    canonical = read(directory / "canonical-state.json")["items"]
    require(state(snapshot.rows) == canonical, "carrier_canonical_state_changed")
    positions = [i for i, item in enumerate(canonical) if item.get("type") == "compaction"]
    require(len(positions) == 1, "carrier_item_count_mismatch")
    item = canonical[positions[0]]
    require(digest(item) == proof["carrier_sha256"], "carrier_identity_changed")
    compacted = next(r for r in snapshot.rows if r["type"] == "compacted")
    return {"item": item, "ordinal": positions[0], "observed_at": compacted.get("timestamp"),
            "thread_id": outcome["thread_id"], "model": previous["model"], "effort": previous["effort"],
            "workspace": previous["workspace"], "carrier_sha256": proof["carrier_sha256"],
            "shared_acquisition_receipts": receipts,
            "pins": {**proof["pins"], str(proof_path.resolve()): reference["proof_sha256"]}}
