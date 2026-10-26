"""Bind selected material and output to the observed fresh native turn format.

File hashes bind bytes, not relationships between independently editable files.
Unknown or ambiguous native formats fail admission without a model call.
"""
import json

from wsc.contracts import digest, require
from wsc.selection_facts import describe
from wsc.span_selection import span_material


def single(values, reason):
    require(len(values) == 1, "generated_selection_" + reason)
    return values[0]


def text(item, block_type):
    content = item.get("content")
    require(isinstance(content, list) and len(content) == 1
            and content[0].get("type") == block_type and isinstance(content[0].get("text"), str),
            "generated_selection_text_shape_unknown")
    return content[0]["text"]


def verify_transcript(snapshot, phase):
    rows = snapshot.rows
    turn_id, thread_id = phase["usage_completion_evidence"]["turn_id"], phase["thread_id"]
    metadata = single([r["payload"] for r in rows if r["type"] == "session_meta"], "session_ambiguous")
    require(metadata.get("id") == thread_id, "generated_selection_session_changed")
    starts = [(i, r["payload"]) for i, r in enumerate(rows)
              if r["type"] == "event_msg" and r["payload"].get("type") == "task_started"]
    ends = [(i, r["payload"]) for i, r in enumerate(rows)
            if r["type"] == "event_msg" and r["payload"].get("type") == "task_complete"]
    start, started = single(starts, "turn_start_ambiguous")
    end, ended = single(ends, "turn_end_ambiguous")
    contexts = [(i, r["payload"]) for i, r in enumerate(rows) if r["type"] == "turn_context"]
    context = single([p for i, p in contexts if p.get("turn_id") == turn_id], "turn_context_ambiguous")
    require(all(i < start or p.get("turn_id") == turn_id for i, p in contexts),
            "generated_selection_turn_context_changed")
    require(start < end and all(p.get("turn_id") == turn_id for p in (started, ended, context)),
            "generated_selection_turn_changed")
    completed = [(i, r["payload"]) for i, r in enumerate(rows)
                 if r["type"] == "event_msg" and r["payload"].get("type") == "item_completed"]
    require(all(start < i < end and p.get("turn_id") == turn_id and p.get("thread_id") == thread_id
                for i, p in completed), "generated_selection_item_turn_changed")
    request_index, request_item = single([(i, p["item"]) for i, p in completed
        if p["item"].get("type") == "UserMessage"], "request_ambiguous")
    request_text = text(request_item, "text")
    request = json.loads(request_text)
    require(isinstance(request, dict) and request.get("operation") == "working_state_selection"
            and isinstance(request.get("material"), dict), "generated_selection_request_unknown")
    inputs = [(i, r["payload"]) for i, r in enumerate(rows) if r["type"] == "response_item"
              and r["payload"].get("type") == "message" and r["payload"].get("role") == "user"
              and r["payload"].get("content") == [{"type": "input_text", "text": request_text}]]
    input_index, _ = single(inputs, "submitted_input_missing_or_ambiguous")
    require(start < input_index < request_index, "generated_selection_input_order_changed")
    finals = [(i, r["payload"]) for i, r in enumerate(rows) if r["type"] == "response_item"
              and r["payload"].get("type") == "message" and r["payload"].get("role") == "assistant"
              and r["payload"].get("phase") == "final_answer"]
    final_index, final = single(finals, "durable_final_ambiguous")
    completed_index, completed_final = single([(i, p["item"]) for i, p in completed
        if p["item"].get("type") == "AgentMessage" and p["item"].get("phase") == "final_answer"],
        "completed_final_ambiguous")
    observed_text = text(final, "output_text")
    reported = phase["finals"][0]
    # Native event and response-item persistence can occur in either order;
    # both must belong after this request and before the durable turn end.
    require(request_index < final_index < end and request_index < completed_index < end and
            final.get("id") and final["id"] == completed_final.get("id") == reported.get("id") and
            observed_text == text(completed_final, "Text") == reported.get("text") == ended.get("last_agent_message"),
            "generated_selection_final_binding_changed")
    proof = {"scope": "fresh_single_turn_native_generation", "turn_id": turn_id,
             "submitted_request_sha256": digest(request), "submitted_material_sha256": digest(request["material"]),
             "final_item_id": final["id"], "final_text_sha256": digest(observed_text)}
    return proof, request


def verify_turn(snapshot, phase, material, prefix, *, max_chars):
    proof, request = verify_transcript(snapshot, phase)
    offered = request["material"]
    expected_material = material
    if "selection_facts" in offered:
        facts = offered["selection_facts"]
        limit = facts.get("serialized_view_limit_bytes") if isinstance(facts, dict) else None
        require(type(limit) is int and limit > 0, "generated_selection_facts_invalid")
        expected_material = {**material, "selection_facts": describe(prefix, limit)}
    require(offered == span_material(expected_material, max_chars=max_chars),
            "generated_selection_submitted_material_changed")
    return proof
