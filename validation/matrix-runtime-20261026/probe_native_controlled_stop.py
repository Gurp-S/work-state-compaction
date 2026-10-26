"""One explicit-stop qualification, no active compact/inject and no application."""
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
import json
import math
import queue
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, usage
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
from native_rollout_snapshot import capture_rollout
from native_turn_accounting import account_turn
from native_application_budget import StudyBudget
from native_controlled_boundary import assess_wait, seal_controlled_stop, stop_event

PARENT = Path('D:/agent-task-runs/native-boundary-capability-20261026-v3')
OUT = Path('D:/agent-task-runs/native-controlled-stop-20261026-v1')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
reg = read(PARENT / 'registration.json')['session']
reg = {**reg, 'workspace': str(WORK), 'sandbox': 'read-only'}
assert file_hash(reg['executable']) == reg['executable_sha256']
envelope = read(PARENT / 'next-admission-envelope.json')
caps = dict(envelope['remaining_limits'])
limits = dict(max_total_tokens=120000, max_responses=4, max_seconds=120)
assert all(caps[k] >= limits[k] for k in limits)
budget = StudyBudget({'protocol/controlled-stop': limits}, caps)
request = '调用 checkpoint_ready 一次，参数为 {}。收到工具结果后，仅返回 {"done":true}。'
tool = dict(type='function', name='checkpoint_ready', description='Host-owned checkpoint boundary. No task file changes.',
    inputSchema=dict(type='object', properties={}, required=[], additionalProperties=False))
parent_hashes = {name: file_hash(PARENT / name) for name in ('result.json', 'next-admission-envelope.json')}
save(OUT / 'registration.json', dict(created_at=datetime.now(timezone.utc).isoformat(), session=reg,
    limits=limits, remaining_study_limits=caps, parent_envelope=envelope, parent_sha256=parent_hashes,
    request=request, dynamic_tool=tool, automatic_retries=0, model_attempts=1,
    application_development=False, formal_BC=False, native_B_changed=False,
    scope='Controlled stop capability only; no installation, continuation or benefit proof',
    intervention='Explicit turn/interrupt only after admitted held callback; never active compact/inject'))
server = opened = turn_id = ticket = gate = held = None
events = []
result = dict(controlled_stop_sealed=False, task_completed=False)
before = b''
terminal = callback_seen = False
begin = time.monotonic()
log = (OUT / 'events.jsonl').open('x', encoding='utf-8')

def record(event):
    if event.get('eof') or event.get('transport_error'):
        raise RuntimeError('native_transport_ended')
    events.append(event)
    log.write(json.dumps(event, ensure_ascii=False) + '\n')
    log.flush()

def interrupt():
    result['interrupt_requested'] = True
    save(OUT / 'interrupt-intent.json', dict(thread_id=opened['thread']['id'], turn_id=turn_id))
    result['interrupt_reply'] = server.call('turn/interrupt',
        dict(threadId=opened['thread']['id'], turnId=turn_id), timeout=8)

try:
    server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / 'stderr.txt', settings=settings(reg))
    server.call('initialize', dict(clientInfo=dict(name='controlled_stop', version='1'), capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    opened = server.call('thread/start', dict(cwd=str(WORK), model=reg['model'], allowProviderModelFallback=False,
        approvalPolicy='never', sandbox='read-only', runtimeWorkspaceRoots=[str(WORK)], ephemeral=False, dynamicTools=[tool]))
    save(OUT / 'thread-start.json', opened)
    assert opened['model'] == reg['model'] and opened['reasoningEffort'] == reg['effort']
    server.call('thread/inject_items', dict(threadId=opened['thread']['id'], items=[dict(type='message', role='developer',
        content=[dict(type='input_text', text=json.dumps(dict(kind='execution_binding',
            current_workspace=str(WORK), execution_mode='read_only')))])]))
    path = Path(opened['thread']['path'])
    wait = time.monotonic() + 3
    while not path.exists() and time.monotonic() < wait:
        time.sleep(.05)
    before = path.read_bytes()
    assert not any(row['type'] == 'token_usage_record' for row in capture_rollout(path).rows)
    ticket, grant = budget.reserve('protocol/controlled-stop', limits)
    save(OUT / 'grant.json', dict(ticket=ticket, limits=grant, ledger=budget.snapshot()))
    turn = server.call('turn/start', dict(threadId=opened['thread']['id'], model=reg['model'], effort=reg['effort'],
        input=[dict(type='text', text=request)]))
    turn_id = turn['turn']['id']
    save(OUT / 'turn-start.json', turn)
    print('One registered controlled-stop turn running', flush=True)
    deadline = time.monotonic() + grant['max_seconds']
    while time.monotonic() < deadline:
        try:
            event = server.event(timeout=.2)
        except queue.Empty:
            continue
        record(event)
        method, params = event.get('method'), event.get('params', {})
        if 'id' in event and method:
            assert method == 'item/tool/call' and not callback_seen, 'unexpected_callback'
            callback_seen = True
            save(OUT / 'held-callback.json', event)
            drain_until = time.monotonic() + 2
            while time.monotonic() < drain_until:
                try:
                    pending = server.event(timeout=.1)
                except queue.Empty:
                    continue
                record(pending)
                assert not ('id' in pending and pending.get('method')), 'concurrent_callback'
            held = path.read_bytes()
            capture_rollout(path, archive=OUT / 'held-native.jsonl')
            members = server.owner.members()
            gate = assess_wait(held, event, events, root_pid=server.proc.pid, owned_members=members)
            save(OUT / 'held-gate.json', dict(**asdict(gate), admitted=gate.admitted, owned_members=members))
            if gate.admitted:
                interrupt()
            else:
                server.send(dict(id=event['id'], result=dict(success=False, contentItems=[dict(type='inputText',
                    text=json.dumps(dict(available=False, reasons=gate.reasons)))])))
                result['rejected_gate_tool_result_sent'] = True
        if method == 'turn/completed' and params['turn']['id'] == turn_id:
            terminal = True
            result['native_turn_status'] = params['turn']['status']
            # Drain late lifecycle events before shutdown; source seal independently rejects new execution.
            drain_until = time.monotonic() + 1
            while time.monotonic() < drain_until:
                try:
                    record(server.event(timeout=.1))
                except queue.Empty:
                    pass
            break
        if method == 'thread/tokenUsage/updated':
            observed = usage(capture_rollout(path).rows, opened['thread']['id'])
            if (observed['response_count'] >= grant['max_responses'] or
                    observed['all_usage']['total_tokens'] >= grant['max_total_tokens']):
                result['failure'] = 'registered_protocol_cap'
                break
except Exception as exc:
    result['error'] = type(exc).__name__ + ':' + str(exc)
finally:
    if server and turn_id and not terminal:
        try:
            if not result.get('interrupt_requested'):
                interrupt()
            wait = time.monotonic() + 4
            while time.monotonic() < wait:
                try:
                    event = server.event(timeout=.2)
                except queue.Empty:
                    continue
                record(event)
                if event.get('method') == 'turn/completed' and event.get('params', {}).get('turn', {}).get('id') == turn_id:
                    terminal = True
        except Exception as exc:
            result['shutdown_error'] = str(exc)
    result['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    log.close()
    if opened:
        closed = capture_rollout(opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
        receipts = usage(closed.rows, opened['thread']['id'])
        complete = False
        if gate and gate.admitted and terminal and not result.get('error'):
            try:
                seal = seal_controlled_stop(gate, held, Path(opened['thread']['path']).read_bytes(), result['cleanup'])
                save(OUT / 'stop-seal.json', asdict(seal))
                save(OUT / 'stop-fact.json', asdict(stop_event(seal)))
                result['controlled_stop_sealed'] = complete = True
            except Exception as exc:
                result['seal_error'] = str(exc)
        elif turn_id:
            ordinary = account_turn(before, Path(opened['thread']['path']).read_bytes(),
                thread_id=opened['thread']['id'], turn_id=turn_id)
            save(OUT / 'ordinary-accounting.json', ordinary)
            complete = ordinary['complete'] and terminal and not result.get('error')
            result['task_completed'] = complete and result.get('native_turn_status') == 'completed'
        phase = dict(receipts=receipts, usage_complete=complete, failure=result.get('failure'),
            seconds=time.monotonic() - begin, task_completed=result['task_completed'],
            accounting_scope='controlled_stop' if result['controlled_stop_sealed'] else 'ordinary_or_unknown')
        save(OUT / 'phase-journal.json', phase)
        if ticket:
            result['settlement'] = budget.settle(ticket, phase)
    result.update(ledger=budget.snapshot(), terminal_observed=terminal, callback_observed=callback_seen,
        application_development=False, receiver_installed=False, whole_campaign_usage_complete=False)
    assert all(file_hash(PARENT / name) == value for name, value in parent_hashes.items())
    save(OUT / 'result.json', result)
    spent = result.get('settlement', {})
    known = spent.get('known_total_tokens', 0)
    responses = spent.get('known_responses', 0)
    complete = spent.get('usage_complete') is True
    remaining = {**caps, 'max_total_tokens': caps['max_total_tokens'] - (known if complete else max(known, limits['max_total_tokens']) if ticket else 0),
        'max_responses': caps['max_responses'] - (responses if complete else max(responses, limits['max_responses']) if ticket else 0),
        'max_seconds': caps['max_seconds'] - math.ceil(time.monotonic() - begin)}
    save(OUT / 'next-admission-envelope.json', dict(remaining_limits=remaining, parent_envelope_sha256=parent_hashes['next-admission-envelope.json'],
        new_known=dict(tokens=known, responses=responses), new_usage_complete=complete,
        old_unknowns_preserved=True, whole_campaign_usage_complete=False,
        reservation_scope='Conservative admission only; not cash balance or upper bound of unknown historical spend'))
print(json.dumps({k: result.get(k) for k in ('controlled_stop_sealed', 'task_completed', 'error', 'seal_error', 'settlement')}, ensure_ascii=False), flush=True)
