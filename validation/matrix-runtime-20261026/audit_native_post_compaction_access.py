"""Actual source order and returned heartbeat prove post-compaction access."""
from pathlib import Path
import json
import re
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_rollout_snapshot import capture_rollout

AREA = Path('D:/agent-task-runs/native-post-compaction-access-20261026-v1')
reg = read(AREA / 'registration.json')
result = read(AREA / 'result.json')
binding = read(AREA / 'post-request-binding.json')
first, post = (read(AREA / (label + '-phase.json')) for label in ('startup', 'post'))
source = capture_rollout(AREA / 'closed-native.jsonl')
rows = source.rows
assert source.metadata['parse_complete'] and result['cleanup']['empty_confirmed'] and 'error' not in result
assert first['usage_complete'] and first['completed'] and post['usage_complete'] and post['completed']
assert first['turn_id'] != post['turn_id'] and first['turn_accounting']['thread_id'] == post['turn_accounting']['thread_id']
assert file_hash(AREA / 'startup-native.jsonl') == binding['source_sha256']
positions = lambda kind, turn: [i for i, r in enumerate(rows) if r['type'] == 'event_msg'
    and r['payload'].get('type') == kind and r['payload'].get('turn_id') == turn]
end_first, start_post, end_post = (positions(kind, turn)[0] for kind, turn in
    [('task_complete', first['turn_id']), ('task_started', post['turn_id']), ('task_complete', post['turn_id'])])
compacts = [(i, r['payload']) for i, r in enumerate(rows) if r['type'] == 'compacted']
assert len(compacts) == 1 and compacts[0][0] < end_first < start_post < end_post
assert first['receipts']['compactor_response_ids'] == [compacts[0][1]['compaction_response_id']]
calls = [(i, r['payload']) for i, r in enumerate(rows) if r['type'] == 'response_item'
    and r['payload'].get('type') in ('function_call', 'custom_tool_call')]
startup_calls = [(i, p) for i, p in calls if i < end_first]
post_calls = [(i, p) for i, p in calls if start_post < i < end_post]
# The first exec yielded and needed a real native wait call; count all calls,
# while distinguishing tool execution from waiting for that existing exec.
assert len(startup_calls) == 2 and [p['name'] for _, p in startup_calls] == ['exec', 'wait']
assert startup_calls[-1][0] < compacts[0][0] and len(post_calls) == 1
assert 'tools.exec_command' in startup_calls[0][1]['input'] and 'tools.write_stdin' not in startup_calls[0][1]['input']
post_position, post_call = post_calls[0]
assert 'tools.write_stdin' in post_call['input'] and 'tools.exec_command' not in post_call['input']
assert re.search(r'session_id\s*:\s*' + str(binding['session_id']) + r'\b', post_call['input'])
outputs = [(i, r['payload']) for i, r in enumerate(rows) if r['type'] == 'response_item'
    and r['payload'].get('type') in ('function_call_output', 'custom_tool_call_output')]
assert len(outputs) == len(calls) and all(out['call_id'] == call['call_id'] and ci < oi
    for (ci, call), (oi, out) in zip(calls, outputs))
assert post_position < outputs[-1][0] < end_post
def text(output):
    return output if isinstance(output, str) else '\n'.join(block['text'] for block in output if block.get('type') == 'input_text')
nonce, pid = reg['nonce'], binding['pid']
assert re.search(r'STATE_READY pid=' + str(pid) + ' nonce=' + nonce, '\n'.join(text(p['output']) for i, p in outputs if i < end_first))
heartbeat = re.findall(r'STATE_TICK pid=' + str(pid) + ' nonce=' + nonce + r' counter=(\d+)', text(outputs[-1][1]['output']))
assert heartbeat
observations = read(AREA / 'process-observations.json')
for stage in ('before_post_compaction_request', 'after_post_compaction_request'):
    observed = [row for row in observations if row['stage'] == stage]
    assert len(observed) == 1 and observed[0]['pid'] == pid and observed[0]['pid_is_owned_live'] and observed[0]['compactions'] == 1
state = result['ledger']
assert not state['study']['uncertain'] and not state['inflight']
assert state['study']['tokens'] == sum(p['receipts']['all_usage']['total_tokens'] for p in (first, post)) == 156789
assert state['study']['responses'] == sum(p['receipts']['response_count'] for p in (first, post)) == 6
audit = dict(format='native_post_compaction_access_v1', native_session=reg['session'],
    same_service_and_thread=True, in_turn_compaction_receipt_bound=True,
    post_compaction_tool_access=True, same_pid_nonce_heartbeat_observed=True,
    all_local_usage_complete=True, known_tokens=156789, responses=6,
    compaction_tokens=first['turn_accounting']['known_compaction_usage']['total_tokens'],
    seconds=result['seconds'], fixture_threshold=32000, application_threshold_qualified=False,
    business_continuation_proven=False, WSC_semantic_or_economic_benefit_proven=False,
    whole_campaign_usage_complete=False, cleanup_empty=True,
    reviewer_adjustment='First offline audit incorrectly assumed exactly two outer calls; actual startup exec yielded and was paired with wait. No model rerun.',
    evidence_scope='One persistent PowerShell command-session across automatic compaction; not all native tools or background workloads',
    inputs_sha256={name: file_hash(AREA / name) for name in ('registration.json', 'controller.py',
        'startup-native.jsonl', 'closed-native.jsonl', 'post-request-binding.json', 'process-observations.json',
        'startup-phase.json', 'post-phase.json', 'result.json')})
save(AREA / 'audit.json', audit)
print(json.dumps(audit, ensure_ascii=False))
