"""Audit semantic availability and exact references after the single model call."""
from pathlib import Path
from contextlib import closing
import sqlite3,json,sys
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from wsc.contracts import encode
OUT=Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1')
OLD=Path('D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1')
with closing(sqlite3.connect('file:'+str(OUT/'state.db')+'?mode=ro',uri=True)) as db:
 events=[json.loads(r[0]) for r in db.execute('SELECT data FROM events ORDER BY seq')]
 body=json.loads(db.execute('SELECT data FROM views ORDER BY rowid DESC LIMIT 1').fetchone()[0])['body']
 records=[json.loads(r[0]) for r in db.execute('SELECT data FROM understandings ORDER BY id,revision')]
with closing(sqlite3.connect('file:'+str(OLD/'state.db')+'?mode=ro',uri=True)) as db:
 old_events=[json.loads(r[0]) for r in db.execute('SELECT data FROM events ORDER BY seq')]
 old_records=[json.loads(r[0]) for r in db.execute('SELECT data FROM understandings ORDER BY id,revision')]
assert events[:201]==old_events and all(r in records for r in old_records)
byid={e['id']:e for e in events};hot={e['id']:e for e in body['sources']}
for row in body['sources']:assert row['text']==byid[row['id']]['text']
for row in body['understandings']+body['clues']:assert set(row['sources'])<=byid.keys()
for excerpt in body['excerpts']:
 text=byid[excerpt['source_id']]['text'][excerpt['start']:excerpt['end']]
 assert sha256(text.encode()).hexdigest()==excerpt['text_sha256']
for event in events:
 if event['kind']=='message' and event['role']=='user':assert hot[event['id']]['text']==event['text']
newfacts=events[201];calibration=events[202];assert newfacts['id'] in hot and calibration['id'] in hot
facts=json.loads(hot[newfacts['id']]['text']);cal=json.loads(hot[calibration['id']]['text'])
assert facts['execution_context']['entry']=='production_panel'
assert facts['visual']['clipping_observed'] is False and facts['visual']['real_wheel_changed_scroll'] is True
assert 'different host' in facts['application_scope']
assert cal['locator_variant']['passed']==36 and cal['negative_control']['failed']==3
new_record=next(r for r in body['understandings'] if r['kind']=='component_calibration_history')
assert calibration['id'] in new_record['sources']
assert all(r['scope']['delivery_stage']=='S3' for r in body['understandings'])
assert len({r['id'] for r in body['understandings']})==len(body['understandings'])
result=read(OUT/'result.json');phase=read(OUT/'phase-journal.json')
assert result['transport_passed'] and not result['ledger']['inflight'] and result['cleanup']['empty_confirmed']
assert phase['usage_complete'] and phase['receipts']['response_count']==1
assert result['rendered_bytes']<=49152 and len(encode(body).encode())<=131072
cold={}
for name in ('material-access','export-access'):
 value=read(OUT/name/'execution.json');assert value['exitCode']==0
 cold[name]=json.loads(value['stdout']);assert cold[name]['passed']
review=dict(selection_evidence_gate_passed=True,old_events_preserved=201,old_record_versions_preserved=4,
 three_prior_understanding_kinds_preserved=True,selected_understandings=len(body['understandings']),
 selected_duplicate_identity_revisions=0,new_component_calibration_record=True,
 explicit_visual_correction_in_understanding=False,
 visual_context_distinction_in_full_hot_source=True,old_visual_record_retained_as_history=True,
 source_references_and_excerpt_hashes_valid=True,user_control_text_complete=True,
 manual_semantic_review=dict(component_27_9_vs_variant_36_0_distinguished=True,negative_3_failure_scope_preserved=True,
 source_scope_dimensions_preserved=True,S3_target_preserved=True,S2_native_incomplete_not_upgraded=True,
 full_project_success_not_claimed=True),
 hot_sources=len(body['sources']),excerpts=len(body['excerpts']),clues=len(body['clues']),
 rendered_previous_bytes=20151,rendered_current_bytes=result['rendered_bytes'],body_bytes=len(encode(body).encode()),
 selection_usage=phase['receipts']['all_usage'],seconds=phase['seconds'],model_calls=1,cold_access=cold,
 full_C_continuation_qualified=False,model_application_of_evidence_proven=False,BC_benefit_proven=False,
 whole_campaign_usage_complete=False,development_started=False,
 next_step='Prepare a bounded real C S3 admission using this package and the calibrated public evidence; no more state-question probes or automatic old-run restart')
save(OUT/'semantic-review.json',review)
print(json.dumps({k:review[k] for k in ('selection_evidence_gate_passed','selected_understandings','rendered_current_bytes','body_bytes','cold_access')},ensure_ascii=False))
