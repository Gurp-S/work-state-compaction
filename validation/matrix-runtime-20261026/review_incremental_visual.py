"""Audit the single completed incremental revision against immutable input evidence."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from native_visual_source_observation import from_probe
from wsc.contracts import encode
AREA=Path('D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1')
PRIOR=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
def state(path):
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        events=[json.loads(row[0]) for row in db.execute('SELECT data FROM events ORDER BY seq')]
        body=json.loads(db.execute('SELECT data FROM views ORDER BY rowid DESC LIMIT 1').fetchone()[0])['body']
    return events,body
old_events,old=state(PRIOR/'state.db')
events,body=state(AREA/'state.db')
result=read(AREA/'result.json'); package=read(AREA/'package.json')
assert result['selection_transport_passed'] and result['source_unchanged'] and result['pins_unchanged']
assert result['cleanup']['empty_confirmed'] and not result['ledger']['inflight']
assert not result['ledger']['study']['uncertain'] and result['ledger']['study']['responses']==1
assert events[:-1]==old_events
by_id={row['id']:row for row in events}
old_records={row['ref']:row for row in old['understandings']}
current_records={row['ref']:row for row in body['understandings']}
assert len(old_records)==3 and all(current_records.get(ref)==row for ref,row in old_records.items())
new=[row for row in body['understandings'] if row['ref'] not in old_records]
assert len(new)==1 and new[0]['previous'] in old_records and new[0]['revision']==2
assert new[0]['kind']=='verification_status'
visual=events[-1]
assert visual['id'].startswith('visual-source-observation:')
assert visual['payload']==read(PRIOR/'current-visual-observation.json')
workspace=Path(read(AREA/'registration.json')['session']['workspace'])
assert from_probe(workspace/'gui',PRIOR/'S2-clipping-check/registration.json',PRIOR/'S2-clipping-check/result.json')==visual['payload']
assert visual['observed_at']==visual['payload']['receipt_file_mtime_utc']
assert any(row['id']==visual['id'] and row['text']==visual['text'] for row in body['sources'])
assert visual['id'] in new[0]['sources']
assert any(visual['id'] in row['sources'] and '裁切' in row['text'] for row in body['clues'])
for record in body['understandings']:
    assert record['scope']==old['understandings'][0]['scope']
    assert all(source in by_id for source in record['sources'])
for clue in body['clues']:
    assert all(source in by_id for source in clue['sources'])
for source in body['sources']:
    assert source['id'] in by_id and source['text']==by_id[source['id']]['text']
from hashlib import sha256
for excerpt in body['excerpts']:
    text=by_id[excerpt['source_id']]['text'][excerpt['start']:excerpt['end']]
    assert sha256(text.encode()).hexdigest()==excerpt['text_sha256']
old_keys={row['key'] for row in old['excerpts']}
assert old_keys <= {row['key'] for row in body['excerpts']}
assert len(encode(package['items']).encode())==result['rendered_bytes']<=49152
assert len(encode(body).encode())<=131072
cold={}
for name in ('material-access','export-access'):
    execution=read(AREA/name/'execution.json')
    assert execution['exitCode']==0
    cold[name]=json.loads(execution['stdout'])
    assert cold[name]['passed'] and not cold[name]['bad']
phase=read(AREA/'phase-journal.json')
assert phase['usage_complete'] and phase['completed'] and not phase['failure']
review=dict(semantic_selection_gate_passed=True,original_event_prefix_unchanged=True,
    prior_understandings_preserved=3,new_versioned_understandings=1,hot_understanding_versions=4,
    duplicate_prior_revision_retained=True,duplicate_revision_semantic_conflict_observed=False,
    specific_clipping_hot=True,visual_evidence_in_whole_source_understanding_clue_and_excerpt=True,
    original_observation_time_preserved=True,time_basis='receipt_file_mtime_not_claimed_exact_probe_start',
    current_source_binding_revalidated=True,source_references_valid=True,excerpt_hashes_valid=True,
    prior_excerpts_retained=len(old_keys),sources=len(body['sources']),excerpts=len(body['excerpts']),clues=len(body['clues']),
    rendered_previous_bytes=read(PRIOR/'result.json')['rendered_bytes'],rendered_bytes=result['rendered_bytes'],
    prepared_body_bytes=len(encode(body).encode()),rendered_limit=49152,prepared_body_limit=131072,
    source_and_pins_unchanged=True,cold_access=cold,model_calls=1,model_usage=phase['receipts']['all_usage'],seconds=phase['seconds'],
    manual_semantic_checks=dict(S3_target_preserved=True,scope_dimensions_preserved=True,S2_9_of_9_automatic_only_preserved=True,
        S2_native_incomplete_preserved=True,clipping_diagnosis_preserved=True,scenario_and_viewport_not_generalized=True,
        historical_receipt_time_preserved_in_original_sources=True,full_visual_qualification_not_claimed=True),
    development_started=False,full_development_qualification_passed=False,BC_benefit_proven=False,
    whole_campaign_usage_complete=False,
    preflight_incident=dict(model_calls=0,preserved_at=str(AREA)+'-preflight-only',
        reason='Existing shared browser runtime directory creation rejected before session registration; reused verified directory'),
    next_step='Zero-model development admission with this sealed package; then separately registered bounded C S3 continuation before B/C.')
save(AREA/'semantic-review.json',review)
print(json.dumps({key:review[key] for key in ('semantic_selection_gate_passed','prior_understandings_preserved','hot_understanding_versions','specific_clipping_hot','rendered_bytes','prepared_body_bytes','cold_access')},ensure_ascii=False))
