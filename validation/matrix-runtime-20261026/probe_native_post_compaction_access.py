"""One two-turn qualification; post-compaction access cannot batch with startup."""
from pathlib import Path
from hashlib import sha256
import json
import math
import queue
import re
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

PARENT = Path('D:/agent-task-runs/native-auto-compaction-20261026-v4')
OUT = Path('D:/agent-task-runs/native-post-compaction-access-20261026-v1')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
reg = {**read(PARENT / 'registration.json')['session'], 'workspace': str(WORK)}
assert file_hash(reg['executable']) == reg['executable_sha256']
parent_hash = file_hash(PARENT / 'next-admission-envelope.json')
caps = read(PARENT / 'next-admission-envelope.json')['remaining_limits']
limits = dict(max_total_tokens=200000, max_responses=8, max_seconds=180)
assert all(caps[key] >= value for key, value in limits.items())
budget = StudyBudget({'protocol/post-compaction-access': limits}, caps)
fixture = WORK / 'state_probe.ps1'
fixture.write_bytes((PARENT / 'workspace/state_probe.ps1').read_bytes())
fixture_hash = file_hash(fixture)
nonce = re.search(r'\$nonce = "([a-f0-9]+)"', fixture.read_text(encoding='utf-8')).group(1)
runtime = 'C:/Program Files/PowerShell/7/pwsh.exe'
request = ('这是原生工具会话测试的启动步骤。仅用exec_command运行：& \'' + runtime +
    '\' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + str(fixture) +
    '"，yield_time_ms=1000，max_output_tokens=40000；若使用functions.exec包装，外层max_output_tokens设50000。'
    '完整返回运行结果，然后仅输出JSON，包含本次返回的session_id和STATE_READY中的实际pid。此步骤只启动和报告，不轮询。')
save(OUT / 'registration.json', dict(session=reg, limits=limits, parent_envelope_sha256=parent_hash,
    auto_compact_threshold=32000, fixture_sha256=fixture_hash, nonce=nonce,
    startup_request=request, automatic_retries=0, registered_turns=2, native_B_changed=False,
    application_development=False, formal_BC=False,
    scope='Actual native session access in a separate turn after observed in-turn auto-compaction; not WSC benefit'))
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
server = opened = None
phases = []
observations = []
begin = time.monotonic()
result = {}
log = (OUT / 'events.jsonl').open('x', encoding='utf-8')

def record(event):
    if event.get('eof') or event.get('transport_error'):
        raise RuntimeError('native_transport_ended')
    log.write(json.dumps(event, ensure_ascii=False) + '\n')
    log.flush()

def output_text(payload):
    output = payload.get('output', '')
    if isinstance(output, str):
        return output
    assert isinstance(output, list), 'unexpected_tool_output_shape'
    return '\n'.join(block['text'] for block in output if block.get('type') == 'input_text')

def observe(label):
    snap = capture_rollout(opened['thread']['path'])
    outputs = '\n'.join(output_text(row['payload']) for row in snap.rows if row['type'] == 'response_item'
        and row['payload'].get('type') in ('custom_tool_call_output', 'function_call_output'))
    ready = re.search(r'STATE_READY pid=(\d+) nonce=' + nonce, outputs)
    if ready:
        pid = int(ready.group(1))
        members = server.owner.members()
        observations.append(dict(stage=label, pid=pid, pid_is_owned_live=pid in members,
            compactions=sum(row['type'] == 'compacted' for row in snap.rows), members=members))

def run_turn(label, text):
    path = Path(opened['thread']['path'])
    before = path.read_bytes()
    base = len(capture_rollout(path).rows)
    ticket, grant = budget.reserve('protocol/post-compaction-access', limits)
    save(OUT / (label + '-grant.json'), dict(ticket=ticket, grant=grant))
    tid = None
    terminal = False
    outcome = dict(label=label)
    try:
        turn = server.call('turn/start', dict(threadId=opened['thread']['id'], model=reg['model'], effort=reg['effort'],
            input=[dict(type='text', text=text)]))
        tid = turn['turn']['id']
        save(OUT / (label + '-turn-start.json'), turn)
        print(label + ' running', flush=True)
        deadline = time.monotonic() + grant['max_seconds']
        while time.monotonic() < deadline:
            try:
                event = server.event(timeout=.25)
            except queue.Empty:
                continue
            record(event)
            method, params = event.get('method'), event.get('params', {})
            assert not ('id' in event and method), 'unexpected_server_callback'
            if method == 'error':
                raise RuntimeError('native_provider_error')
            if method in ('thread/tokenUsage/updated', 'item/completed'):
                observe(label)
                current = usage(capture_rollout(path).rows[base:], opened['thread']['id'])
                if current['response_count'] >= grant['max_responses'] or current['all_usage']['total_tokens'] >= grant['max_total_tokens']:
                    outcome['failure'] = 'registered_protocol_cap'
                    break
            if method == 'turn/completed' and params['turn']['id'] == tid:
                terminal = True
                outcome['completed'] = params['turn']['status'] == 'completed'
                break
    except Exception as exc:
        outcome['error'] = type(exc).__name__ + ':' + str(exc)
    finally:
        if tid and not terminal:
            try:
                server.call('turn/interrupt', dict(threadId=opened['thread']['id'], turnId=tid), timeout=8)
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    try:
                        event = server.event(timeout=.2)
                    except queue.Empty:
                        continue
                    record(event)
                    if event.get('method') == 'turn/completed' and event.get('params', {}).get('turn', {}).get('id') == tid:
                        terminal = True
            except Exception as exc:
                outcome['interrupt_error'] = str(exc)
        snap = capture_rollout(path, archive=OUT / (label + '-native.jsonl'))
        proof = account_turn(before, path.read_bytes(), thread_id=opened['thread']['id'], turn_id=tid) if tid else None
        receipts = usage(snap.rows[base:], opened['thread']['id'])
        outcome.update(turn_id=tid, usage_complete=bool(proof and proof['complete'] and terminal and not outcome.get('error')),
            receipts=receipts, turn_accounting=proof, seconds=time.monotonic()-begin)
        outcome['settlement'] = budget.settle(ticket, outcome)
        save(OUT / (label + '-phase.json'), outcome)
        phases.append(outcome)
    return outcome

try:
    server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / 'stderr.txt',
        settings=settings(reg) + ['model_auto_compact_token_limit=32000'])
    server.call('initialize', dict(clientInfo=dict(name='post_compaction_access', version='1'), capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    preflight = server.call('command/exec', dict(command=[runtime, '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
        'Bypass', '-File', str(fixture), '-ProbeOnly'], cwd=str(WORK), sandboxPolicy=dict(type='readOnly'), timeoutMs=10000))
    save(OUT / 'preflight.json', preflight)
    assert preflight.get('exitCode') == 0 and 'SHELL_READY' in preflight.get('stdout', ''), 'shell_preflight_failed'
    opened = server.call('thread/start', dict(cwd=str(WORK), model=reg['model'], allowProviderModelFallback=False,
        approvalPolicy='never', sandbox='read-only', runtimeWorkspaceRoots=[str(WORK)], ephemeral=False, dynamicTools=[]))
    save(OUT / 'thread-start.json', opened)
    assert opened['model'] == reg['model'] and opened['reasoningEffort'] == reg['effort']
    server.call('thread/inject_items', dict(threadId=opened['thread']['id'], items=[dict(type='message', role='developer',
        content=[dict(type='input_text', text=json.dumps(dict(kind='execution_binding', current_workspace=str(WORK), execution_mode='read_only')))])]))
    path = Path(opened['thread']['path'])
    deadline = time.monotonic() + 3
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    startup = run_turn('startup', request)
    assert startup['usage_complete'] and startup.get('completed') and not startup.get('failure'), 'startup_not_complete'
    snap = capture_rollout(path)
    assert any(row['type'] == 'compacted' for row in snap.rows), 'automatic_compaction_not_observed'
    final = [row['payload'] for row in snap.rows if row['type'] == 'response_item'
        and row['payload'].get('type') == 'message' and row['payload'].get('role') == 'assistant'][-1]
    facts = json.loads(final['content'][0]['text'])
    assert type(facts.get('session_id')) is int and type(facts.get('pid')) is int, 'startup_handle_invalid'
    observe('before_post_compaction_request')
    assert observations[-1]['pid_is_owned_live'] and observations[-1]['pid'] == facts['pid'], 'startup_pid_not_owned'
    post_request = ('现在检查刚才已存在的工具会话。仅调用write_stdin一次，session_id=' + str(facts['session_id']) +
        '，chars为空，yield_time_ms=1000，max_output_tokens=2000。根据本次实际输出返回JSON：state_survived、pid、nonce、counter。此步骤不启动新进程。')
    save(OUT / 'post-request-binding.json', dict(session_id=facts['session_id'], pid=facts['pid'], request=post_request,
        source_sha256=file_hash(path), first_turn_id=startup['turn_id']))
    post = run_turn('post', post_request)
    observe('after_post_compaction_request')
    result['post_request_completed'] = post.get('completed', False)
except Exception as exc:
    result['error'] = type(exc).__name__ + ':' + str(exc)
finally:
    result['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    log.close()
    if opened:
        capture_rollout(opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
    save(OUT / 'process-observations.json', observations)
    assert file_hash(fixture) == fixture_hash and file_hash(PARENT / 'next-admission-envelope.json') == parent_hash
    state = budget.snapshot()
    result.update(ledger=state, phase_count=len(phases), whole_campaign_usage_complete=False,
        application_development=False, access_verdict='pending independent source audit', seconds=time.monotonic()-begin)
    save(OUT / 'result.json', result)
    unknown = state['study']['uncertain'] or bool(state['inflight'])
    known, responses = state['study']['tokens'], state['study']['responses']
    save(OUT / 'next-admission-envelope.json', dict(remaining_limits=dict(
        max_total_tokens=caps['max_total_tokens']-(max(known, limits['max_total_tokens']) if unknown else known),
        max_responses=caps['max_responses']-(max(responses, limits['max_responses']) if unknown else responses),
        max_seconds=caps['max_seconds']-math.ceil(result['seconds'])),
        new_known=dict(tokens=known, responses=responses), new_usage_complete=not unknown,
        old_unknowns_preserved=True, whole_campaign_usage_complete=False, parent_envelope_sha256=parent_hash,
        scope='Conservative admission only, not balance or upper bound of historical unknown spend'))
print(json.dumps({k: result.get(k) for k in ('post_request_completed', 'error', 'phase_count', 'seconds')}, ensure_ascii=False), flush=True)
