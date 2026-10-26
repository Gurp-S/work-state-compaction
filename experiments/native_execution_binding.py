"""Current execution identity at the shared paid native phase boundary."""
import json
from pathlib import Path

from native_evidence import digest, import_evidence, records, state


def require(value, reason):
    if not value:
        raise ValueError(reason)


def report_execution_item(workspace, file_manifest):
    return {"type": "message", "role": "developer", "content": [{"type": "input_text", "text":
        json.dumps({"kind": "experimental_execution_binding", "current_workspace": str(Path(workspace).resolve()),
            "current_file_manifest_sha256": digest(file_manifest), "execution_mode": "read_only",
            "source_history": "Archived observations; embedded environment records describe their original execution."},
            ensure_ascii=False, sort_keys=True)}]}


def verify_execution_binding(reg, opened):
    # Selection-only calls do not continue the archived business task. They have
    # a separate generation/source/future-execution scope in their request.
    if reg.get("purpose") == "automatic_selection_generation_only":
        return
    require(reg.get("purpose") in {"C_qualification", "comparison", "carrier_acquisition",
        "archived_handoff_downstream_diagnostic_not_C_qualification",
        "continuity_task_diagnostic_not_comparison"}, "native_execution_purpose_unregistered")
    item = reg.get("common_workspace_fact") or reg.get("execution_fact")
    require(isinstance(item, dict) and item.get("role") == "developer", "native_execution_fact_missing")
    try:
        fact = json.loads(item["content"][0]["text"])
        current = Path(fact["current_workspace"])
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ValueError("native_execution_fact_invalid") from exc
    require(current.is_absolute() and current.resolve() == Path(reg["workspace"]).resolve(),
            "native_execution_fact_workspace_mismatch")
    if reg.get('accounting_scope') == 'fork_append_only_turn':
        from native_fork_phase import verify_fork_execution
        return verify_fork_execution(reg, opened, current, item)
    rows = records(opened["thread"]["path"])
    contexts = [r["payload"] for r in rows if r["type"] == "turn_context"]
    require(contexts and Path(contexts[-1]["cwd"]).resolve() == current.resolve(),
            "native_execution_runtime_workspace_mismatch")
    history = state(rows)
    require(history and import_evidence(history[-1:], [item])["matched"],
            "native_execution_fact_not_current_tail")
