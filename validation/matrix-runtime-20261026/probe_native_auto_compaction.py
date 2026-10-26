"""One in-turn auto-compaction/tool-session probe; not a business comparison."""
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

PARENT = Path('D:/agent-task-runs/native-auto-compaction-20261026-v3')
OUT = Path('D:/agent-task-runs/native-auto-compaction-20261026-v4')
OUT.mkdir(exist_ok=False)
WORK = OUT / 'workspace'
WORK.mkdir()
registered = read(Path('D:/agent-task-runs/native-controlled-stop-20261026-v1/registration.json'))['session']
reg = {key: registered[key] for key in ('executable', 'executable_sha256', 'model', 'effort', 'host_feature_overrides')}
reg['workspace'] = str(WORK)
assert file_hash(reg['executable']) == reg['executable_sha256']
parent_hash = file_hash(PARENT / 'next-admission-envelope.json')
caps = read(PARENT / 'next-admission-envelope.json')['remaining_limits']
limits = dict(max_total_tokens=200000, max_responses=8, max_seconds=180)
assert all(caps[key] >= value for key, value in limits.items())
budget = StudyBudget({'protocol/auto-compaction': limits}, caps)
nonce = sha256(str(OUT).encode()).hexdigest()[:20]
runtime_executable = 'C:/Program Files/PowerShell/7/pwsh.exe'
fixture = WORK / 'state_probe.ps1'
fixture.write_text('param([switch]$ProbeOnly)\n'
    'if ($ProbeOnly) { [Console]::WriteLine("SHELL_READY"); exit 0 }\n'
    f'$nonce = "{nonce}"\n'
    '[Console]::WriteLine("STATE_READY pid=$PID nonce=$nonce")\n'
    '[Console]::WriteLine("DIAGNOSTIC_SAMPLE_BEGIN")\n'
    'for ($i=0; $i -lt 750; $i++) {\n'
    ' [Console]::WriteLine([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$i))))\n'
    '}\n'
    '[Console]::WriteLine("DIAGNOSTIC_SAMPLE_END")\n'
    'for ($i=0; $i -lt 300; $i++) {\n'
    ' [Console]::WriteLine("STATE_TICK pid=$PID nonce=$nonce counter=$i")\n'
    ' Start-Sleep -Seconds 1\n'
    '}\n', encoding='utf-8')
fixture_hash = file_hash(fixture)
request = ('这是原生会话工具状态测试。使用 exec_command 运行：& \'' + runtime_executable + '\' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + str(fixture) +
    '"，yield_time_ms=1000，max_output_tokens=40000。若用functions.exec包装，外层max_output_tokens也设为50000，完整返回该工具结果。'
    '随后用这一次运行返回的session_id调用write_stdin一次，chars为空，yield_time_ms=1000，max_output_tokens=1000。'
    '根据第二次工具返回是否含STATE_TICK判断进程状态仍可访问。最终仅输出JSON，包含state_survived、session_id和实际pid。不要另起进程替代该session。')
save(OUT / 'registration.json', dict(session=reg, limits=limits, parent_envelope_sha256=parent_hash,
    auto_compact_threshold=32000, threshold_scope='Protocol fixture only; does not change proposed application threshold 96000',
    runtime_executable=runtime_executable, preflight_required='native readOnly command/exec exact script ProbeOnly before model reservation',
    fixture_sha256=fixture_hash, nonce=nonce, request=request, automatic_retries=0, model_attempts=1,
    native_B_changed=False, application_development=False, formal_BC=False,
    evidence_scope='In-turn native automatic compaction and existing native command-session continuity only'))
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
server = opened = turn_id = ticket = None
before = b''
terminal = False
result = {}
begin = time.monotonic()
log = (OUT / 'events.jsonl').open('x', encoding='utf-8')
observations = []

def record(event):
    if event.get('eof') or event.get('transport_error'):
        raise RuntimeError('native_transport_ended')
    log.write(json.dumps(event, ensure_ascii=False) + '\n')
    log.flush()

def observe_process():
    snap = capture_rollout(opened['thread']['path'])
    outputs = '\n'.join(str(row['payload'].get('output', '')) for row in snap.rows
        if row['type'] == 'response_item' and row['payload'].get('type') in ('custom_tool_call_output', 'function_call_output'))
    ready = re.search(r'STATE_READY pid=(\d+) nonce=' + nonce, outputs)
    compact = sum(row['type'] == 'compacted' for row in snap.rows)
    if ready and (not observations or compact != observations[-1]['compactions']):
        pid = int(ready.group(1))
        members = server.owner.members()
        observations.append(dict(compactions=compact, pid=pid, owned_members=members, pid_is_owned_live=pid in members))

try:
    server = OwnedNativeRPC(reg['executable'], cwd=WORK, stderr_path=OUT / 'stderr.txt',
        settings=settings(reg) + ['model_auto_compact_token_limit=32000'])
    server.call('initialize', dict(clientInfo=dict(name='auto_compaction_probe', version='1'), capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    preflight = server.call('command/exec', dict(command=[runtime_executable, '-NoProfile', '-NonInteractive',
        '-ExecutionPolicy', 'Bypass', '-File', str(fixture), '-ProbeOnly'],
        cwd=str(WORK), sandboxPolicy=dict(type='readOnly'), timeoutMs=10000), timeout=15)
    save(OUT / 'interpreter-preflight.json', preflight)
    assert preflight.get('exitCode') == 0 and 'SHELL_READY' in preflight.get('stdout', ''), 'native_shell_preflight_failed'
    config = server.call('config/read', dict(cwd=str(WORK), includeLayers=False))
    assert config['config'].get('model_auto_compact_token_limit') == 32000
    save(OUT / 'threshold-readback.json', dict(value=32000, origin=config['origins'].get('model_auto_compact_token_limit')))
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
    before = path.read_bytes()
    ticket, grant = budget.reserve('protocol/auto-compaction', limits)
    save(OUT / 'grant.json', dict(ticket=ticket, limits=grant))
    turn = server.call('turn/start', dict(threadId=opened['thread']['id'], model=reg['model'], effort=reg['effort'],
        input=[dict(type='text', text=request)]))
    turn_id = turn['turn']['id']
    save(OUT / 'turn-start.json', turn)
    print('One automatic-compaction/tool-session turn running', flush=True)
    deadline = time.monotonic() + grant['max_seconds']
    while time.monotonic() < deadline:
        try:
            event = server.event(timeout=.25)
        except queue.Empty:
            continue
        record(event)
        method, params = event.get('method'), event.get('params', {})
        assert not ('id' in event and method), 'unexpected_dynamic_callback'
        if method == 'error':
            raise RuntimeError('native_error:' + json.dumps(params))
        if method in ('thread/tokenUsage/updated', 'item/completed'):
            observe_process()
            ledger = usage(capture_rollout(path).rows, opened['thread']['id'])
            if ledger['response_count'] >= grant['max_responses'] or ledger['all_usage']['total_tokens'] >= grant['max_total_tokens']:
                result['failure'] = 'registered_protocol_cap'
                break
        if method == 'turn/completed' and params['turn']['id'] == turn_id:
            terminal = True
            result['native_turn_status'] = params['turn']['status']
            observe_process()
            break
except Exception as exc:
    result['error'] = type(exc).__name__ + ':' + str(exc)
finally:
    if server and turn_id and not terminal:
        try:
            server.call('turn/interrupt', dict(threadId=opened['thread']['id'], turnId=turn_id), timeout=8)
            until = time.monotonic() + 4
            while time.monotonic() < until:
                try:
                    event = server.event(timeout=.2)
                except queue.Empty:
                    continue
                record(event)
                if event.get('method') == 'turn/completed' and event.get('params', {}).get('turn', {}).get('id') == turn_id:
                    terminal = True
        except Exception as exc:
            result['interrupt_error'] = str(exc)
    result['cleanup'] = server.close() if server else dict(empty_confirmed=True, process_started=False)
    log.close()
    save(OUT / 'process-observations.json', observations)
    if opened:
        closed = capture_rollout(opened['thread']['path'], archive=OUT / 'closed-native.jsonl')
        proof = account_turn(before, Path(opened['thread']['path']).read_bytes(), thread_id=opened['thread']['id'], turn_id=turn_id) if turn_id else None
        ledger = usage(closed.rows, opened['thread']['id'])
        result['compaction_observed'] = any(row['type'] == 'compacted' for row in closed.rows)
        complete = bool(proof and proof['complete'] and terminal and not result.get('error'))
        phase = dict(receipts=ledger, usage_complete=complete, completed=result.get('native_turn_status') == 'completed',
            seconds=time.monotonic() - begin, failure=result.get('failure'), turn_accounting=proof)
        save(OUT / 'phase-journal.json', phase)
        if ticket:
            result['settlement'] = budget.settle(ticket, phase)
    assert file_hash(fixture) == fixture_hash and file_hash(PARENT / 'next-admission-envelope.json') == parent_hash
    result.update(terminal_observed=terminal, ledger=budget.snapshot(), whole_campaign_usage_complete=False,
        application_development=False, evidence_scope='Raw run; semantic/session verdict requires separate source audit')
    save(OUT / 'result.json', result)
    spent = result.get('settlement', {})
    known, responses = spent.get('known_total_tokens', 0), spent.get('known_responses', 0)
    complete = spent.get('usage_complete') is True
    save(OUT / 'next-admission-envelope.json', dict(remaining_limits=dict(
        max_total_tokens=caps['max_total_tokens']-(known if complete else max(known, limits['max_total_tokens']) if ticket else 0),
        max_responses=caps['max_responses']-(responses if complete else max(responses, limits['max_responses']) if ticket else 0),
        max_seconds=caps['max_seconds']-math.ceil(time.monotonic()-begin)),
        parent_envelope_sha256=parent_hash, new_known=dict(tokens=known, responses=responses),
        new_usage_complete=complete, old_unknowns_preserved=True, whole_campaign_usage_complete=False,
        scope='Conservative admission only, not balance or historical unknown upper bound'))
print(json.dumps({k: result.get(k) for k in ('native_turn_status', 'error', 'settlement')}, ensure_ascii=False), flush=True)
