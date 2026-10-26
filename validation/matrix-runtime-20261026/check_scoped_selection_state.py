"""Real archived evidence: same S2 GUI hash, distinct whole-workspace scope."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_scoped_selection_state import build, load, as_event

COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
reg = read(COMMON / 'registration.json')
stage = read(COMMON / 'staged/payload-C.json')['stages'][2]
value = build(COMMON / 'staged/frozen-workspace', COMMON / 'S2-source-acceptance/registration.json',
    COMMON / 'S2-grade.json', reg['expected_checks']['a3']['2'], stage)
path = OUT / 'scoped-selection-state.json'
save(path, value)
reference = dict(path=str(path), sha256=file_hash(path))
assert load(reference, receiving_workspace=COMMON / 'staged/frozen-workspace') == value
assert value['receipt_to_snapshot_gui'] == dict(status='same_content', equal=True)
assert value['workspace_to_gui'] == dict(status='different_scopes', equal=None)
assert all(value['auxiliary_to_snapshot'].values())
assert value['original_S2_receipt']['observed_at'] == read(COMMON / 'S2-grade.json')['observed_at']
assert value['requested_delivery_stage'] == 'S3'
assert value['visual_coverage'] == 'not_attested_by_this_automatic_receipt'
assert as_event(value).payload['original_S2_native_turn_completed'] is False
try:
    load(reference, receiving_workspace=OUT / 'workspace')
    raise AssertionError('old S2 receipt accepted as current S3 source')
except ValueError as error:
    assert str(error) == 'scoped_selection_receiving_source_changed'
save(OUT / 'scoped-selection-state-check.json', dict(passed=True, same_gui_receipt_binding=True,
    different_scopes_not_marked_different_versions=True, original_observation_time_preserved=True,
    current_delivery='S3', visual_coverage_still_unknown=True, reference=reference,
    model_calls=0, enabled_in_new_trial=False, scope='Offline factual binding repair; no regenerated understanding or development success proof'))
print(dict(passed=True, model_calls=0, receipt_matches_S2_gui=True, stage='S3', visual_scope='unknown'))
