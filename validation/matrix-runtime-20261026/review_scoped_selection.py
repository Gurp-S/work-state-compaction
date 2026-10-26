"""Freeze factual declaration checks and the observed semantic-readiness limitation."""
from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save
from wsc.contracts import encode

OUT = Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
OLD = Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
draft = read(OUT/'generation/compiled-draft.json')
scoped = read(OLD/'scoped-selection-state.json')
known = {value['scope']: value['sha256'] for value in (scoped['workspace_binding'], scoped['gui_source_binding'])}
declared = []
for record in draft['new_understandings']:
    value = record.get('scope')
    declared.append(dict(kind=record['kind'], declaration_present=value is not None,
        hash_matches_declared_scope=value is not None and known.get(value.get('manifest_scope'))==value.get('source_manifest_sha256'),
        delivery_stage_matches=value is not None and value.get('delivery_stage')==scoped['requested_delivery_stage']))
con = sqlite3.connect(OUT/'state.db')
body = json.loads(con.execute('SELECT data FROM views ORDER BY rowid DESC LIMIT 1').fetchone()[0])['body']
source_ids = set(row['id'] for row in body['sources'])
source_ids.update(source for row in body['understandings'] for source in row['sources'])
source_ids.update(source for row in body['clues'] for source in row['sources'])
source_ids.update(row['source_id'] for row in body.get('excerpts',[]))
historical_negatives = []
for data, in con.execute('SELECT data FROM events ORDER BY seq'):
    row = json.loads(data); text = row.get('text') or ''
    if row['kind']=='result' and ('page content is clipped' in text or 'clipped normal/1440/light:' in text):
        historical_negatives.append(dict(source_id=row['id'], referenced_in_hot_state=row['id'] in source_ids))
con.close()
old_bytes = read(OLD/'prepared.json')['rendered_bytes']
new_bytes = read(OUT/'result.json')['rendered_bytes']
probe = read(OUT/'S2-clipping-check/result.json')
review = dict(declared_scopes=declared, original_understanding_errors_corrected=True,
    manual_text_review=dict(S3_target_explicit=True, workspace_and_gui_scopes_distinguished=True,
        S2_nine_automatic_checks_retained=True, S2_visual_not_claimed_complete=True, S2_native_turn_not_claimed_complete=True),
    historical_negative_sources=historical_negatives,
    specific_clipping_diagnosis_hot=any(item['referenced_in_hot_state'] for item in historical_negatives),
    all_original_sources_still_cold_available=True, current_S2_clipping_reproduced=probe['clipping_observed'],
    rendered_before_bytes=old_bytes, rendered_after_bytes=new_bytes, prepared_body_bytes=len(encode(body).encode()),
    semantic_readiness='pending_incremental_visual_observation_revision', development_gate_passed=False,
    generation_attempts=1, development_calls=0, additional_semantic_review_model_calls=0,
    scope='Single candidate: stage/scope declarations corrected; active specific visual negative still requires revision. No B/C benefit proof.')
assert all(row['hash_matches_declared_scope'] and row['delivery_stage_matches'] for row in declared)
assert probe['source_unchanged'] and probe['errors']==[] and probe['clipping_observed']
assert historical_negatives and not review['specific_clipping_diagnosis_hot']
save(OUT/'semantic-review.json',review)
print(dict(declared_scope_and_stage_passed=True,rendered_before=old_bytes,rendered_after=new_bytes,
    specific_negative_hot=False,clipping_reproduced=True,development_gate_passed=False))
