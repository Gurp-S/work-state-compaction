"""Evidence for complete usage in one fresh native experiment phase.

This recognizes the observed native rollout format; an unknown format fails
qualification instead of supplying an estimated complete total.
"""
from native_evidence import FIELDS


def completion_evidence(snapshot, receipts, *, turn_id, compact):
    reasons = []
    rows = snapshot.rows
    if not snapshot.metadata["parse_complete"]:
        reasons.append("rollout_incomplete")
    completions = [i for i, row in enumerate(rows) if row["type"] == "event_msg"
                   and row["payload"].get("type") == "task_complete"
                   and row["payload"].get("turn_id") == turn_id]
    if not turn_id or len(completions) != 1:
        reasons.append("durable_turn_completion_missing_or_ambiguous")
    usage_rows = [(i, row["payload"]) for i, row in enumerate(rows)
                  if row["type"] == "token_usage_record"]
    if not usage_rows or any(p.get("turn_id") != turn_id for _, p in usage_rows):
        reasons.append("phase_usage_turn_binding_unknown")
    if completions and usage_rows and usage_rows[-1][0] >= completions[0]:
        reasons.append("usage_after_turn_completion")
    seen, cumulative = set(), dict.fromkeys(FIELDS, 0)
    for _, payload in usage_rows:
        rid = payload["response_id"]
        if rid in seen:
            continue
        seen.add(rid)
        for field in FIELDS:
            cumulative[field] += payload["usage"][field]
        if payload.get("turn_token_usage") != cumulative:
            reasons.append("receipt_cumulative_usage_mismatch")
            break
    if compact:
        compacted = [(i, r["payload"]) for i, r in enumerate(rows) if r["type"] == "compacted"]
        expected = usage_rows[-1][1] if usage_rows else None
        if (len(compacted) != 1 or len(usage_rows) != 1 or
                compacted[0][1].get("latest_token_usage_record") != expected or
                compacted[0][1].get("compaction_response_id") != (expected or {}).get("response_id") or
                not completions or not usage_rows[0][0] < compacted[0][0] < completions[0]):
            reasons.append("compaction_terminal_usage_binding_unknown")
    else:
        counts = [(i, r["payload"].get("info")) for i, r in enumerate(rows)
                  if r["type"] == "event_msg" and r["payload"].get("type") == "token_count"]
        info = counts[-1][1] if counts else None
        if (not isinstance(info, dict) or info.get("total_token_usage") != receipts["all_usage"] or
                not usage_rows or info.get("last_token_usage") != usage_rows[-1][1]["usage"] or
                not completions or not usage_rows[-1][0] < counts[-1][0] < completions[0]):
            reasons.append("terminal_cumulative_usage_mismatch")
    return {"complete": not reasons, "reasons": list(dict.fromkeys(reasons)), "turn_id": turn_id,
            "scope": "fresh_single_turn_native_phase", "rollout_sha256": snapshot.metadata["sha256"]}
