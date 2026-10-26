"""Recheck archived inputs and separate imported history from new public items."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "experiments"), str(ROOT / "src")]
from native_evidence import file_hash, usage
from native_rollout_snapshot import capture_rollout
from native_usage_boundary import completion_evidence
from wsc.contracts import encode

HERE = Path(__file__).resolve().parent
report = json.loads((HERE / "cost-analysis.json").read_text(encoding="utf-8"))
for path, expected in report["input_sha256"].items():
    assert file_hash(path) == expected, path
for key, directory in (
    ("generation", "D:/agent-task-runs/wsc-span-selection-20261023-v1/generation"),
    ("continuation", "D:/agent-task-runs/wsc-generated-covered-C-20261023-v1/C/continuation"),
):
    root = Path(directory)
    phase = json.loads((root / "phase-outcome.json").read_text(encoding="utf-8"))
    snapshot = capture_rollout(root / "rollout.jsonl")
    receipts = usage(snapshot.rows, phase["thread_id"], line_numbers=snapshot.line_numbers)
    turn = phase["usage_completion_evidence"]["turn_id"]
    assert completion_evidence(snapshot, receipts, turn_id=turn, compact=False)["complete"]
    assert receipts == phase["receipts"]
    starts = [i for i, r in enumerate(snapshot.rows) if r["type"] == "event_msg"
              and r["payload"].get("type") == "task_started" and r["payload"].get("turn_id") == turn]
    assert len(starts) == 1
    responses, pending = [], []
    for i, row in enumerate(snapshot.rows):
        if i <= starts[0]:
            continue
        item = row["payload"]
        if row["type"] == "response_item" and (item.get("type") in ("function_call", "custom_tool_call")
                or item.get("type") == "message" and item.get("role") == "assistant"):
            pending.append({"line": snapshot.line_numbers[i], "type": item["type"],
                "name": item.get("name"), "phase": item.get("phase"),
                "serialized_bytes": len(encode(item).encode("utf-8"))})
        if row["type"] == "token_usage_record":
            responses.append({"response_id": item["response_id"], "usage": item["usage"],
                              "new_public_items": pending})
            pending = []
    report[key]["responses"] = responses
    report[key]["public_item_scope"] = "after matching durable task_started; imported messages excluded"
report["analysis_correction"] = "The first draft grouped imported assistant history with C response 1; this revision excludes it. Token totals were unchanged."
(HERE / "cost-analysis-reviewed.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"input_hashes_verified": len(report["input_sha256"]),
                  "combined_usage": report["combined_usage"], "new_model_calls": 0}))
