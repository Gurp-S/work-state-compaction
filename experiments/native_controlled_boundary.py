"""Opt-in local boundary admission; does not interrupt, compact or publish.

Only an exclusive exec-wrapped, empty-argument checkpoint is supported. Kernel
membership and a complete lifecycle prefix come from the owning controller.
This is not proof of remote service quiescence or of semantic completeness.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from native_rollout_snapshot import parse_rollout
from native_turn_accounting import vector, plus
from native_evidence import FIELDS, usage, import_evidence
from wsc.contracts import digest, encode, Event


@dataclass(frozen=True)
class BoundaryGate:
    thread_id: str
    turn_id: str
    callback_id: str
    root_pid: int
    source_sha256: str
    callback_digest: str
    events_digest: str
    response_ids: tuple
    reasons: tuple

    @property
    def admitted(self):
        return not self.reasons


@dataclass(frozen=True)
class StopSeal:
    thread_id: str
    turn_id: str
    source_sha256: str
    callback_digest: str
    receipts_json: str

    @property
    def receipts(self):
        return json.loads(self.receipts_json)


def stop_event(seal):
    if not isinstance(seal, StopSeal):
        raise ValueError('controlled_stop_seal_required')
    value = dict(kind='native_controlled_stop_v1', thread_id=seal.thread_id, turn_id=seal.turn_id,
        source_sha256=seal.source_sha256, observation_stage='source_sealed_after_controlled_interrupt',
        known_tokens=seal.receipts['all_usage']['total_tokens'], responses=seal.receipts['response_count'],
        task_completion_observed=False)
    return Event('controlled-stop:' + seal.source_sha256, 'control', value, text=encode(value), control=True)


def _exclusive_exec(item, tool):
    if item.get('type') != 'custom_tool_call' or item.get('name') != 'exec':
        return False
    if not re.fullmatch(r'[A-Za-z_$][\w$]*', tool):
        return False
    name = r'([A-Za-z_$][\w$]*)'
    invoke = r'await\s+tools\.' + re.escape(tool) + r'\s*\(\s*\{\s*\}\s*\)'
    # Full-match allowlist: no other expressions, timers, promises or commands.
    assigned = r'\s*(?:const|let)\s+' + name + r'\s*=\s*' + invoke + r'\s*;\s*text\s*\(\s*\1\s*\)\s*;?\s*'
    return bool(re.fullmatch(assigned, item.get('input', ''))
        or re.fullmatch(r'\s*' + invoke + r'\s*;?\s*', item.get('input', '')))


def assess_wait(raw, callback, events, *, root_pid, owned_members, tool='checkpoint_ready'):
    snapshot = parse_rollout(raw)
    params = callback.get('params', {})
    thread, turn, call = (params.get(k, '') for k in ('threadId', 'turnId', 'callId'))
    reasons = []
    def check(ok, reason):
        if not ok:
            reasons.append(reason)
    check(snapshot.metadata['parse_complete'], 'source_incomplete')
    meta = [r['payload'] for r in snapshot.rows if r['type'] == 'session_meta']
    check(len(meta) == 1 and meta[0].get('id') == thread, 'thread_identity_unknown')
    check(callback.get('method') == 'item/tool/call' and 'id' in callback and turn and call
        and params.get('tool') == tool and params.get('arguments') == {}, 'callback_binding_invalid')
    starts = [i for i, r in enumerate(snapshot.rows) if r['type'] == 'event_msg'
        and r['payload'].get('type') == 'task_started' and r['payload'].get('turn_id') == turn]
    check(len(starts) == 1, 'turn_start_unknown')
    start = starts[0] if len(starts) == 1 else len(snapshot.rows)
    tail = snapshot.rows[start:]
    check(not any(r['type'] == 'compacted' or r['type'] == 'event_msg'
        and r['payload'].get('type') == 'task_started' and r['payload'].get('turn_id') != turn
        for r in tail), 'other_execution_started')
    check(not any(r['type'] == 'event_msg' and r['payload'].get('type') in ('turn_aborted', 'task_complete')
        and r['payload'].get('turn_id') == turn for r in tail), 'turn_already_terminal')
    receipts = [(i, r['payload']) for i, r in enumerate(snapshot.rows) if r['type'] == 'token_usage_record'
        and r['payload'].get('thread_id') == thread and r['payload'].get('turn_id') == turn]
    check(bool(receipts), 'provider_receipt_missing')
    running = dict.fromkeys(FIELDS, 0)
    ids = []
    for _, record in receipts:
        rid = record.get('response_id')
        check(isinstance(rid, str) and rid and rid not in ids, 'response_identity_invalid')
        ids.append(rid)
        if vector(record.get('usage')):
            value = record['usage']
            check(value['cached_input_tokens'] <= value['input_tokens']
                and value['input_tokens'] + value['output_tokens'] == value['total_tokens'],
                'response_usage_inconsistent')
            running = plus(running, record['usage'])
            check(record.get('turn_token_usage') == running, 'response_counter_gap')
        else:
            check(False, 'response_usage_invalid')
    last = receipts[-1][0] if receipts else start
    previous = receipts[-2][0] + 1 if len(receipts) > 1 else start
    call_types = ('custom_tool_call', 'function_call')
    outputs = ('custom_tool_call_output', 'function_call_output')
    recent = [r['payload'] for r in snapshot.rows[previous:last] if r['type'] == 'response_item'
        and r['payload'].get('type') in call_types]
    check(len(recent) == 1 and _exclusive_exec(recent[0], tool), 'checkpoint_not_exclusive_exec')
    pending = {}; seen_calls = set()
    for row in tail:
        if row['type'] != 'response_item':
            continue
        item = row['payload']; kind = item.get('type', '')
        if kind in call_types:
            key = item.get('call_id')
            check(key and key not in seen_calls, 'tool_call_identity_invalid')
            seen_calls.add(key)
            pending[key] = item
        elif kind in outputs:
            key = item.get('call_id')
            check(key in pending, 'tool_output_unpaired')
            pending.pop(key, None)
        elif kind.endswith('_call'):
            check(False, 'unsupported_native_call_type')
    check(len(pending) == 1 and recent and list(pending.values()) == recent, 'other_native_calls_pending')
    check(not any(r['type'] == 'response_item' and (r['payload'].get('type') in call_types
        or r['payload'].get('type') == 'reasoning') for r in snapshot.rows[last + 1:]), 'unreceipted_model_output')
    active = {}; began = 0
    inert = {'userMessage', 'agentMessage', 'reasoning', 'plan'}
    for event in events:
        p = event.get('params', {}); method = event.get('method')
        if method == 'turn/started' and p.get('turn', {}).get('id') == turn:
            began += 1
        if method == 'turn/started':
            check(p.get('threadId') == thread and p.get('turn', {}).get('id') == turn,
                'foreign_execution_event')
        if method == 'turn/completed' and p.get('turn', {}).get('id') == turn:
            check(False, 'lifecycle_turn_terminal')
        if method not in ('item/started', 'item/completed'):
            continue
        item = p.get('item', {})
        if item.get('type') in inert:
            continue
        check(p.get('threadId') == thread and p.get('turnId') == turn, 'foreign_operation_event')
        key = item.get('id')
        if method == 'item/started':
            check(key and key not in active, 'operation_event_gap')
            active[key] = item
        else:
            check(key in active, 'operation_event_gap')
            active.pop(key, None)
    check(began == 1, 'lifecycle_turn_start_unknown')
    check(len(active) == 1 and call in active and active[call].get('type') == 'dynamicToolCall'
        and active[call].get('tool') == tool, 'operations_not_drained')
    check(type(root_pid) is int and root_pid > 0 and owned_members is not None
        and list(owned_members) == [root_pid], 'owned_processes_not_drained_or_unknown')
    return BoundaryGate(thread, turn, call, root_pid, snapshot.metadata['sha256'], digest(callback),
        digest(events), tuple(ids), tuple(dict.fromkeys(reasons)))


def seal_controlled_stop(gate, held_raw, closed_raw, cleanup):
    def require(ok, reason):
        if not ok:
            raise ValueError(reason)
    require(gate.admitted, 'controlled_boundary_not_admitted')
    require(sha256(held_raw).hexdigest() == gate.source_sha256, 'controlled_boundary_source_changed')
    require(closed_raw.startswith(held_raw), 'controlled_stop_source_prefix_changed')
    held, closed = parse_rollout(held_raw), parse_rollout(closed_raw)
    require(closed.metadata['parse_complete'], 'controlled_stop_source_incomplete')
    receipts = lambda snap: [r for r in snap.rows if r['type'] == 'token_usage_record']
    require(receipts(held) == receipts(closed), 'controlled_stop_late_or_changed_receipts')
    new = closed.rows[len(held.rows):]
    require(not any(r['type'] in ('compacted',) or r['type'] == 'event_msg'
        and r['payload'].get('type') == 'task_started' for r in new), 'controlled_stop_extra_execution')
    require(not any(r['type'] == 'response_item' and r['payload'].get('type') not in
        ('custom_tool_call_output', 'function_call_output') for r in new), 'controlled_stop_new_model_or_control_material')
    ends = [r['payload'] for r in new if r['type'] == 'event_msg'
        and r['payload'].get('type') == 'turn_aborted' and r['payload'].get('turn_id') == gate.turn_id]
    require(len(ends) == 1 and ends[0].get('reason') == 'interrupted', 'controlled_stop_not_explicit_interrupt')
    cancelled = [r['payload'] for r in new if r['type'] == 'event_msg'
        and r['payload'].get('type') == 'item_completed'
        and r['payload'].get('item', {}).get('id') == gate.callback_id]
    require(len(cancelled) == 1 and cancelled[0].get('turn_id') == gate.turn_id
        and cancelled[0]['item'].get('type') == 'DynamicToolCall'
        and cancelled[0]['item'].get('status') == 'failed'
        and cancelled[0]['item'].get('success') is False
        and cancelled[0]['item'].get('error') == 'dynamic tool call was cancelled before receiving a response',
        'controlled_stop_unanswered_callback_not_cancelled')
    pending = set()
    for row in closed.rows:
        item = row.get('payload', {})
        if row['type'] == 'response_item':
            if item.get('type') in ('function_call', 'custom_tool_call'):
                pending.add(item['call_id'])
            elif item.get('type') in ('function_call_output', 'custom_tool_call_output'):
                require(item.get('call_id') in pending, 'controlled_stop_unpaired_output')
                pending.remove(item['call_id'])
    require(not pending, 'controlled_stop_calls_unpaired')
    require(cleanup.get('empty_confirmed') is True and cleanup.get('root_pids') == [gate.root_pid]
        and cleanup.get('members_after_termination') == [], 'controlled_stop_processes_not_closed')
    own = [(i, r) for i, r in enumerate(closed.rows) if r['type'] == 'token_usage_record'
        and r['payload'].get('thread_id') == gate.thread_id and r['payload'].get('turn_id') == gate.turn_id]
    return StopSeal(gate.thread_id, gate.turn_id, closed.metadata['sha256'], gate.callback_digest,
        encode(usage([r for _, r in own], gate.thread_id, line_numbers=[closed.line_numbers[i] for i, _ in own])))


def reserve_committed_receiver(core, operation_id, receiver_id, receiver_raw, seal, budget, arm, limits):
    """Reserve, never execute, after exact no-tail publication/import verification.

No native HostPort is implemented here. An actual installer must produce the
receipt through WSC install/confirm before this gate can grant execution.
"""
    from wsc.publication import operation, check_evidence
    from wsc.store import getmeta
    marker = stop_event(seal)
    observed = parse_rollout(receiver_raw)
    def require(ok, reason):
        if not ok:
            raise ValueError(reason)
    require(observed.metadata['parse_complete'], 'controlled_receiver_history_incomplete')
    metas = [r['payload'] for r in observed.rows if r['type'] == 'session_meta']
    require(len(metas) == 1 and metas[0].get('id') == receiver_id and receiver_id != seal.thread_id,
        'controlled_receiver_identity_invalid')
    require(not any(r['type'] == 'token_usage_record' or r['type'] == 'event_msg'
        and r['payload'].get('type') == 'task_started' for r in observed.rows), 'controlled_receiver_not_idle')
    with core.store.transaction() as db:
        op = operation(db, operation_id)
        require(op['state'] == 'confirmed' and op['receipt'] is not None, 'controlled_publication_unconfirmed')
        package, receipt = op['package'], op['receipt']
        require(receipt.get('receiver') == receiver_id and receipt.get('evidence_accessible') is True,
            'controlled_receiving_receipt_invalid')
        require(getmeta(db, 'head') == op['view_id'] and getmeta(db, 'generation') == receipt.get('generation')
            and getmeta(db, 'cursor') == package['binding']['cut'] and getmeta(db, 'mode') == 'active',
            'controlled_publication_not_current')
        require(getmeta(db, 'control_epoch') == receipt.get('control_epoch'), 'controlled_control_changed')
        require(db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == package['binding']['cut'],
            'controlled_uncovered_tail_present')
        row = db.execute('SELECT data FROM events WHERE id=?', (marker.id,)).fetchone()
        require(row is not None and json.loads(row[0])['payload'] == marker.payload
            and marker.id in package['evidence'], 'controlled_stop_not_in_publication')
        items = [r['payload'] for r in observed.rows if r['type'] == 'response_item']
        imported = import_evidence(items, package['items'])
        require(package['items'] and imported['matched'] and
            imported['start_ordinal'] + len(package['items']) == len(items), 'controlled_import_not_exact_suffix')
        check_evidence(core, package)
        state = budget.snapshot()
        require(state['study']['uncertain'] is False and arm in state['arms'] and not state['arms'][arm]['stopped']
            and not any(v['arm'] == arm for v in state['inflight'].values()), 'controlled_budget_unsettled')
        # The same StudyBudget performs cumulative reservation; no replacement ledger.
        return budget.reserve(arm, limits)
