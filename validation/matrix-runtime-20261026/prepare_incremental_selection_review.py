"""Prepare retained working records plus new source-bound negative evidence; no generation."""
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save
from native_visual_source_observation import from_probe, as_event
from native_incremental_candidate import frontier
from wsc import WSC, Store

AREA = Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
OUT = AREA / 'incremental-review-input'
OUT.mkdir(exist_ok=False)
reg = read(AREA / 'registration.json')['session']
value = from_probe(Path(reg['workspace'])/'gui', AREA/'S2-clipping-check/registration.json', AREA/'S2-clipping-check/result.json')
save(AREA/'current-visual-observation.json', value)
source = sqlite3.connect('file:'+str(AREA/'state.db')+'?mode=ro',uri=True)
target = sqlite3.connect(OUT/'state.db');source.backup(target);source.close();target.close()
core = WSC(Store(OUT/'state.db',session_id='a3/scoped-selection-v1/C',workspace=reg['workspace']),access=lambda *args:True)
before = core.capture()
previous = read(AREA/'continuation.json')
core.ingest([as_event(value)])
snapshot = core.capture()
assert tuple(snapshot.events[:-1]) == before.events
assert snapshot.understandings == before.understandings
material, offered = frontier(core,snapshot,previous,OUT/'cold-public')
assert len(offered['understandings']) == 3
assert offered['previous_selection']['clues']
assert material['events'][-1]['text_in_frontier'] and '"clipping_observed":true' in material['events'][-1]['text']
save(OUT/'offered.json',offered)
save(OUT/'previous.json',previous)
save(OUT/'result.json',dict(prepared=True,prior_records_unchanged=3,prior_clues_retained=True,
    original_event_prefix_unchanged=True,appended_source_bound_visual_observation=True,
    clipping_observed=value['clipping_observed'],source_gui_sha256=value['source_binding']['sha256'],
    model_calls=0,scope='Offline input for later incremental revision, not a second generation or development proof'))
print(dict(prepared=True,old_records_preserved=3,clipping_observed=value['clipping_observed'],model_calls=0))
