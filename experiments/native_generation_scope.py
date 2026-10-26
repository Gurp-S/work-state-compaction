"""Producer-observed execution identity, separate from the generator's cwd."""
from pathlib import Path

from wsc.contracts import require


def generation_scope(snapshot, phase, generator_workspace):
    require(snapshot.metadata["parse_complete"] and
            snapshot.metadata["sha256"] == phase["rollout_sha256"], "generation_scope_rollout_changed")
    turn = phase["usage_completion_evidence"]["turn_id"]
    contexts = [r["payload"] for r in snapshot.rows if r["type"] == "turn_context"
                and r["payload"].get("turn_id") == turn]
    require(len(contexts) == 1, "generation_scope_context_ambiguous")
    context = contexts[0]
    cwd = context.get("cwd")
    require(isinstance(cwd, str) and bool(cwd) and Path(cwd).is_absolute(),
            "generation_scope_workspace_unknown")
    return {"generator_workspace": str(Path(generator_workspace).resolve()),
            "generator_role": "selection_generation_without_task_execution",
            "source_execution": {"thread_id": phase["thread_id"], "turn_id": turn,
                                 "workspace": cwd, "rollout_sha256": snapshot.metadata["sha256"],
                                 "scope": "historically_observed_execution_context"},
            "continuation_execution": {"status": "not_registered", "workspace": None}}
