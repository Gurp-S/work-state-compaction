"""Independently bound verdict; a final-answer claim is not tool-state proof."""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_rollout_snapshot import capture_rollout

AREA = Path('D:/agent-task-runs/native-auto-compaction-20261026-v4')
phase = read(AREA / 'phase-journal.json')
result = read(AREA / 'result.json')
registration = read(AREA / 'registration.json')
source = capture_rollout(AREA / 'closed-native.jsonl')
events = [json.loads(line) for line in (AREA / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
rows = source.rows
compacts = [(i, row['payload']) for i, row in enumerate(rows) if row['type'] == 'compacted']
assert source.metadata['parse_complete'] and phase['usage_complete'] and phase['turn_accounting']['complete']
assert phase['completed'] and result['cleanup']['empty_confirmed'] and len(compacts) == 1
position, compact = compacts[0]
receipts = phase['receipts']
assert receipts['response_count'] == 3 and receipts['all_usage']['total_tokens'] == 88803
assert receipts['compactor_response_ids'] == [compact['compaction_response_id']]
assert phase['turn_accounting']['known_compaction_usage']['total_tokens'] == 48120
calls = [(i, row['payload']) for i, row in enumerate(rows) if row['type'] == 'response_item'
    and row['payload'].get('type') in ('custom_tool_call', 'function_call')]
assert len(calls) == 1 and calls[0][0] < position and 'await tools.write_stdin' in calls[0][1]['input']
outputs = [(i, row['payload']) for i, row in enumerate(rows) if row['type'] == 'response_item'
    and row['payload'].get('type') in ('custom_tool_call_output', 'function_call_output')]
assert len(outputs) == 1 and outputs[0][0] < position and outputs[0][1]['call_id'] == calls[0][1]['call_id']
observations = read(AREA / 'process-observations.json')
assert len(observations) == 2 and [r['compactions'] for r in observations] == [0, 1]
assert observations[0]['pid'] == observations[1]['pid'] and all(r['pid_is_owned_live'] for r in observations)
final = [row['payload'] for row in rows if row['type'] == 'response_item'
    and row['payload'].get('type') == 'message' and row['payload'].get('role') == 'assistant'][-1]
claim = json.loads(final['content'][0]['text'])
assert claim['state_survived'] is True and claim['pid'] == observations[0]['pid']
audit = dict(scope='One in-turn automatic compaction with complete receipts; OS process continuity only',
    runtime_auto_compaction=True, same_thread_and_turn_continued=True, normal_completion=True,
    known_tokens=88803, known_responses=3, compaction_tokens=48120,
    background_pid_alive_before_after=True, post_compaction_native_tool_access_proven=False,
    reason='Startup and polling were in the same outer exec, whose result preceded compaction; no post-compaction tool call',
    model_success_claim_is_sufficient=False,
    raw_result_default_flags_are_not_verdict=True,
    source_outer_output_text_bytes=sum(len(block['text'].encode()) for _, p in outputs
        for block in p['output'] if block.get('type') == 'input_text'),
    streamed_command_output_bytes=sum(len(e['params'].get('delta', '').encode()) for e in events
        if e.get('method') == 'item/commandExecution/outputDelta'),
    output_scope='Outer persisted output is a content-block list; sum its input_text bytes. Stream deltas and stored tool text have different envelopes; byte totals alone do not prove delivery completeness.',
    supersedes_audit='audit.json retained: used str(list) byte count and contained an incorrect one-byte characterization',
    fixture_unchanged=file_hash(Path(registration['session']['workspace']) / 'state_probe.ps1') == registration['fixture_sha256'],
    whole_campaign_usage_complete=False, WSC_semantic_benefit_proven=False, formal_BC=False,
    cumulative_probe_known=dict(tokens=46767+88803, responses=2+3, model_trials=2, preflight_only_attempts=2),
    inputs_sha256={name: file_hash(AREA / name) for name in ('controller.py', 'registration.json',
        'closed-native.jsonl', 'events.jsonl', 'process-observations.json', 'phase-journal.json', 'result.json')})
assert audit['fixture_unchanged']
save(AREA / 'audit-v2.json', audit)
print(json.dumps(audit, ensure_ascii=False))
