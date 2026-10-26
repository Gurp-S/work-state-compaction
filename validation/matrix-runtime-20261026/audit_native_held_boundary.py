"""Audit the one dynamic waiting-point experiment; preserve incomplete accounting."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_campaign_envelope import qualification_envelope
AREA=Path('D:/agent-task-runs/native-boundary-capability-20261026-v3')
callback=read(AREA/'held-callback.json');held=capture_rollout(AREA/'held-native.jsonl');closed=capture_rollout(AREA/'closed-native.jsonl')
r=read(AREA/'result.json');phase=read(AREA/'phase-journal.json')
assert r['cleanup']['empty_confirmed'] and r['ledger']['study']['uncertain'] and not r['ledger']['inflight']
receipts=[row['payload'] for row in held.rows if row['type']=='token_usage_record']
assert len(receipts)==1 and receipts[0]['thread_id']==callback['params']['threadId'] and receipts[0]['turn_id']==callback['params']['turnId']
assert receipts[0]['usage']==receipts[0]['turn_token_usage']
events=[json.loads(l) for l in (AREA/'events.jsonl').read_text(encoding='utf-8').splitlines()]
assert any(e.get('method')=='item/started' and e.get('params',{}).get('item',{}).get('id')==callback['params']['callId']
 and e['params']['item']['type']=='dynamicToolCall' for e in events)
messages=[row['payload'] for row in closed.rows if row['type']=='response_item' and row['payload'].get('type')=='message']
marker_persisted = any('boundary_probe_marker' in json.dumps(v) for v in messages)
control=[row['payload'] for row in closed.rows if row['type']=='event_msg' and row['payload'].get('type') in ('task_started','task_complete','turn_aborted')]
original=callback['params']['turnId'];aborted=[v for v in control if v.get('turn_id')==original and v['type']=='turn_aborted']
assert len(aborted)==1 and aborted[0]['reason']=='replaced'
started=[v for v in control if v['type']=='task_started'];assert len(started)==2
assert not any(row['type']=='compacted' for row in closed.rows)
preflights=[]
for version in ('v1','v2'):
 p=Path('D:/agent-task-runs/native-boundary-capability-20261026-'+version)
 value=read(p/'result.json')
 assert value['ledger']['study']['tokens']==0 and value['ledger']['arms']['protocol/held-tool']['started'] is None
 assert value['cleanup']['empty_confirmed']
 preflights.append(dict(path=str(p),model_turn_started=False,known_model_tokens=0,error=value.get('error')))
review=dict(real_model_attempts=1,known_response_count=phase['receipts']['response_count'],known_usage=phase['receipts']['all_usage'],
 elapsed_seconds=phase['seconds'],complete_usage=None,whole_campaign_usage_complete=False,
 dynamic_callback_withheld=True,matching_receipt_at_wait=True,
 dynamic_item_event_observed=True,thread_read_full_tool_graph_proven=False,
 held_injection_accepted=True,injected_marker_in_persisted_history=marker_persisted,next_model_receipt_of_marker_proven=False,
 native_compact_accepted=True,original_turn_replaced=True,new_compaction_turn_started=True,
 compaction_completion_observed=False,original_task_normally_completed=False,
 safe_in_place_checkpoint_proven=False,quiescent_application_boundary_proven=False,
 cleanup_empty=True,old_ledgers_unchanged=True,preflight_failures=preflights,
 source_notes='Thread read listed user/reasoning only at this point; dynamic item was visible in lifecycle events. Provider settlement alone does not prove all tool side effects idle.',
 probe_controller_limitation='Watched original turn termination, then closed server; newly started compaction aborted. The resulting unknown usage remains frozen.',
 next_step='Do not connect compact/start at held tool to production; specify controlled handoff, multi-operation drain, publication rollback and provider accounting before a new probe')
save(AREA/'audit.json',review)
envelope=qualification_envelope(r['ledger'],[],phase['seconds'])
envelope.update(whole_campaign_usage_complete=False,old_unknowns_preserved=True,prior_result=dict(path=str(AREA/'result.json'),sha256=file_hash(AREA/'result.json')))
save(AREA/'next-admission-envelope.json',envelope)
print({k:review[k] for k in ('real_model_attempts','known_response_count','known_usage','matching_receipt_at_wait','original_turn_replaced','compaction_completion_observed','safe_in_place_checkpoint_proven')})
print(envelope['remaining_limits'])
