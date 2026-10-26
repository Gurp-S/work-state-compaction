"""Append-only, turn-local accounting for resumed native threads.

Response receipts include compaction spend. Native token_count totals observed
in this format exclude it, so those counters are checked separately, not used
as the bill. An incomplete phase retains known receipts and has no known total.
"""
from native_evidence import FIELDS, usage
from native_rollout_snapshot import parse_rollout


def vector(value):
    return isinstance(value, dict) and all(type(value.get(k)) is int and value[k] >= 0 for k in FIELDS)


def plus(left, right):
    return {k: left[k] + right[k] for k in FIELDS}


def admit_resumed_turn(before_raw, *, thread_id):
    """Live resumed execution needs an observed baseline before spending."""
    snapshot = parse_rollout(before_raw)
    metas = [r["payload"] for r in snapshot.rows if r["type"] == "session_meta"]
    prior = [r["payload"] for r in snapshot.rows if r["type"] == "token_usage_record"]
    counts = [r["payload"].get("info") for r in snapshot.rows if r["type"] == "event_msg"
              and r["payload"].get("type") == "token_count"]
    if not snapshot.metadata["parse_complete"] or len(metas) != 1 or metas[0].get("id") != thread_id:
        raise ValueError("native_resumed_accounting_source_unknown")
    if (not prior or prior[-1].get("thread_id") != thread_id or not vector(prior[-1].get("thread_token_usage"))
            or not counts or not vector((counts[-1] or {}).get("total_token_usage"))
            or any(not isinstance(p.get("response_id"), str) or not p["response_id"] for p in prior)):
        raise ValueError("native_resumed_accounting_baseline_unknown")
    return snapshot


def account_turn(before_raw, after_raw, *, thread_id, turn_id, inherited=None):
    before, after = parse_rollout(before_raw), parse_rollout(after_raw)
    reasons = []
    zero = dict.fromkeys(FIELDS, 0)

    def check(ok, reason):
        if not ok:
            reasons.append(reason)
        return bool(ok)

    prefix_ok = check(after_raw.startswith(before_raw), "turn_source_prefix_changed")
    check(before.metadata["parse_complete"] and after.metadata["parse_complete"], "turn_rollout_incomplete")
    meta = [r["payload"] for r in after.rows if r["type"] == "session_meta"]
    check(len(meta) == 1 and meta[0].get("id") == thread_id, "turn_thread_identity_unknown")
    inherited_valid = inherited is not None and check(
        isinstance(inherited, dict) and vector(inherited.get('thread')) and vector(inherited.get('display'))
        and isinstance(inherited.get('response_ids'), list)
        and all(isinstance(rid, str) and rid for rid in inherited['response_ids'])
        and len(meta) == 1 and isinstance(meta[0].get('history_base'), dict),
        'turn_inherited_baseline_invalid')
    prior = [r["payload"] for r in before.rows if r["type"] == "token_usage_record"]
    check(not any(p.get("turn_id") == turn_id for p in prior), "turn_already_started_at_boundary")
    check(not any(r["type"] == "event_msg" and r["payload"].get("turn_id") == turn_id
                  and r["payload"].get("type") == "task_started" for r in before.rows),
          "turn_already_started_at_boundary")
    base = prior[-1].get("thread_token_usage") if prior else (inherited['thread'] if inherited_valid else zero)
    if not check(vector(base), "turn_thread_counter_baseline_unknown"):
        base = zero
    old_ids = {p.get("response_id") for p in prior}
    if inherited_valid:
        old_ids.update(inherited['response_ids'])
    counts = [r["payload"].get("info") for r in before.rows if r["type"] == "event_msg"
              and r["payload"].get("type") == "token_count"]
    display_base = ((counts[-1] or {}).get("total_token_usage") if counts else
                    ((inherited['display'] if inherited_valid else zero) if not prior else None))
    begin = len(before.rows) if prefix_ok else len(after.rows)
    rows = after.rows[begin:]
    lines = after.line_numbers[begin:]
    starts = [i for i, r in enumerate(rows) if r["type"] == "event_msg"
              and r["payload"].get("type") == "task_started"]
    ends = [i for i, r in enumerate(rows) if r["type"] == "event_msg"
            and r["payload"].get("type") == "task_complete"]
    check(len(starts) == 1 and rows[starts[0]]["payload"].get("turn_id") == turn_id,
          "turn_start_missing_or_ambiguous")
    check(len(ends) == 1 and rows[ends[0]]["payload"].get("turn_id") == turn_id,
          "turn_completion_missing_or_ambiguous")
    receipts, positions, accepted, duplicates = {}, {}, [], []
    running, thread_running = zero, base
    for i, row in enumerate(rows):
        if row["type"] != "token_usage_record":
            continue
        p = row["payload"]
        rid = p.get("response_id")
        valid = check(bool(rid) and isinstance(rid, str) and vector(p.get("usage")), "turn_receipt_invalid")
        if not valid:
            continue
        valid &= check(p["usage"]["cached_input_tokens"] <= p["usage"]["input_tokens"],
                       "turn_receipt_cache_invalid")
        valid &= check(p.get("thread_id") == thread_id and p.get("turn_id") == turn_id,
                       "turn_receipt_identity_mismatch")
        valid &= check(rid not in old_ids, "turn_response_reused_from_history")
        check(len(starts) == 1 and starts[0] < i and (not ends or i < ends[0]),
              "turn_receipt_outside_execution")
        if not valid:
            continue
        if rid in receipts:
            duplicates.append(rid)
            check(receipts[rid] == p, "turn_duplicate_receipt_conflict")
            continue
        receipts[rid], positions[rid] = p, i
        accepted.append((i, row))
        running = plus(running, p["usage"])
        thread_running = plus(thread_running, p["usage"])
        check(p.get("turn_token_usage") == running, "turn_cumulative_receipt_gap")
        check(p.get("thread_token_usage") == thread_running, "turn_thread_counter_gap")
    check(bool(receipts), "turn_no_usage_receipts")
    compact_ids, compact_rows, compact_sum = [], [], zero
    for i, row in enumerate(rows):
        if row["type"] != "compacted":
            continue
        p = row["payload"]
        rid = p.get("compaction_response_id")
        ok = check(rid in receipts and p.get("latest_token_usage_record") == receipts.get(rid)
                   and positions.get(rid, i) < i and (not ends or i < ends[0]),
                   "turn_compaction_receipt_unbound")
        ok &= check(rid not in compact_ids, "turn_compaction_receipt_reused")
        if ok:
            compact_ids.append(rid)
            compact_rows.append((i, row))
            compact_sum = plus(compact_sum, receipts[rid]["usage"])
    normal_sum = {k: running[k] - compact_sum[k] for k in FIELDS}
    if receipts:
        last_id = list(receipts)[-1]
        candidates = [(i, r["payload"].get("info")) for i, r in enumerate(rows)
                      if r["type"] == "event_msg" and r["payload"].get("type") == "token_count"
                      and positions[last_id] < i and (not ends or i < ends[0])]
        info = candidates[-1][1] if candidates else None
        if last_id not in compact_ids:
            check(vector(display_base), "turn_display_counter_baseline_unknown")
            check(isinstance(info, dict) and info.get("last_token_usage") == receipts[last_id]["usage"]
                  and vector(display_base) and info.get("total_token_usage") == plus(display_base, normal_sum),
                  "turn_terminal_counter_mismatch")
        elif candidates:
            # A compaction reset may have a synthetic last_token_usage, but its
            # displayed cumulative cost cannot include an unreceipted later call.
            check(isinstance(info, dict) and vector(display_base)
                  and info.get("total_token_usage") == plus(display_base, normal_sum),
                  "turn_post_compaction_counter_mismatch")
    # Reuse receipt validation and field accounting without unrelated historical
    # turns. Compaction records are bound above before they enter this ledger.
    selected = [(i, r) for i, r in accepted]
    selected += compact_rows
    selected.sort(key=lambda pair: pair[0])
    ledger = usage([r for _, r in selected], thread_id, line_numbers=[lines[i] for i, _ in selected])
    reasons = list(dict.fromkeys(reasons))
    return {"complete": not reasons, "reasons": reasons, "thread_id": thread_id, "turn_id": turn_id,
            "scope": "append_only_single_turn_with_in_turn_compaction",
            "before": before.metadata, "after": after.metadata, "receipts": ledger,
            "known_usage": ledger["all_usage"], "complete_usage": None if reasons else ledger["all_usage"],
            "known_normal_usage": normal_sum, "known_compaction_usage": compact_sum,
            "duplicate_response_ids": duplicates,
            "inherited_thread_counter": base, "display_counter_baseline": display_base,
            "historical_response_count": len(old_ids)}
