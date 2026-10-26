"""Admit all retained native threads before any experimental inference.

The gate compares actual native bootstrap records, not launch parameters alone.
It never edits native prompts, plugin configuration, credentials or permissions.
"""
from native_evidence import digest, import_evidence, records, usage
from native_group_admission import NativeGroupAdmission

MEMBERS = frozenset(("compaction", "B", "C"))
CONFIG_FIELDS = ("model", "modelProvider", "reasoningEffort", "cwd", "sandbox",
                 "approvalPolicy", "serviceTier", "runtimeWorkspaceRoots")


def observe(opened, controls):
    thread = opened["thread"]
    rows = records(thread["path"])
    meta = [r["payload"] for r in rows if r["type"] == "session_meta"]
    contexts = [r["payload"] for r in rows if r["type"] == "turn_context"]
    items = [r["payload"] for r in rows if r["type"] == "response_item"]
    evidence = import_evidence(items, controls)
    if len(meta) != 1 or not contexts or not evidence["matched"]:
        raise ValueError("native_admission_evidence_missing")
    prefix = items[:evidence["start_ordinal"]]
    host = {"base_instructions_sha256": digest(meta[0]["base_instructions"]),
        "dynamic_tools": meta[0].get("dynamic_tools"),
        "bootstrap_messages": [{k: item[k] for k in ("type", "role", "content") if k in item}
                               for item in prefix],
        "native_configuration": {k: opened.get(k) for k in CONFIG_FIELDS},
        "runtime_configuration": {k: contexts[-1].get(k) for k in
                                  ("model", "effort", "cwd", "approval_policy", "sandbox_policy")}}
    return {"thread_id": thread["id"], "rollout_path": thread["path"], "host": host,
            "controls_sha256": digest(controls), "prefix_sha256": digest(prefix),
            "response_count": usage(rows, thread["id"])["response_count"]}


class PairAdmission(NativeGroupAdmission):
    def __init__(self, observations):
        super().__init__(observations, members=MEMBERS, label="native_pair")
