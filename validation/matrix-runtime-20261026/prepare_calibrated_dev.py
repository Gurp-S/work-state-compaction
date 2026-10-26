"""Prepare one real S3 use of the sealed calibrated selection, no regeneration."""
from pathlib import Path
import sys,sqlite3
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from native_application_session import NativeApplicationSession
from wsc import WSC,Store
from wsc.publication import check_evidence
OUT=Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
SELECT=Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
assert read(SELECT/'semantic-review.json')['selection_evidence_gate_passed']
assert read(SELECT/'result.json')['cleanup']['empty_confirmed']
assert read(Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1/result.json'))['parallel_writable_native_admission_passed']
reg={**read(SELECT/'session-registration.json'),'sandbox':'workspace-write'}
payload=read(COMMON/'staged/payload-C.json')
reg.update(parent_thread_id=payload['common_prefix']['reset_parent_thread_id'],
 before_turn_id=payload['common_prefix']['reset_before_turn_id'],parent_paths=payload['registration']['parent_paths'])
OUT.mkdir(exist_ok=False)
measurer=NativeApplicationSession(reg,OUT/'preparation-only')
assert measurer.source_manifest()==reg['initial_manifest']
from contextlib import closing
with closing(sqlite3.connect('file:'+str(SELECT/'state.db')+'?mode=ro',uri=True)) as src:
 with closing(sqlite3.connect(OUT/'state.db')) as dst:src.backup(dst)
core=WSC(Store(OUT/'state.db',session_id='a3/calibrated-selection-v1/C',workspace=reg['workspace']),access=lambda *a:True)
package=read(SELECT/'package.json');check_evidence(core,package)
assert package['binding']['workspace']==reg['workspace']
save(OUT/'package.json',package)
save(OUT/'prepared.json',dict(registration=reg,request=payload['stages'][2]['request'],
 package=str(OUT/'package.json'),package_sha256=file_hash(OUT/'package.json'),
 original_draft=str(SELECT/'generation/compiled-draft.json'),original_draft_sha256=file_hash(SELECT/'generation/compiled-draft.json'),
 source_review=str(SELECT/'semantic-review.json'),source_review_sha256=file_hash(SELECT/'semantic-review.json'),
 source_package_unchanged=True,model_calls=0,scope='Same frozen S2 and original S3 request; sealed new selection and calibrated host'))
save(OUT/'policy-adoption.json',dict(user_choice='采用共享剩余时间（推荐）',ordinary_time_seconds=2700,
 arm_time_seconds=2700,arm_tokens=6000000,arm_responses=120,old_failed_ledger_resumed=False,historical_unknowns_preserved=True))
save(OUT/'verification-plan.json',dict(registered_before_model=True,
 checks=['native_normal_completion','official_cumulative_S1_S3','supplemental_concurrency_failure','supplemental_chart_date_keyboard','production_panel_clipping_normal_1440'],
 public_action_audit=['applicable_baseline_use','old_failure_chasing_vs_legitimate_reverification','host_applicability_use'],
 native_B_unchanged=True,formal_BC=False,automatic_retries=0,
 hypothesis='New source-bound calibration facts may prevent unnecessary investigation of stale selectors and old host clipping while preserving S3 implementation quality',
 success_is_not='A causal native comparison or full eight-stage task qualification'))
print(dict(prepared=True,selection_regenerated=False,model_calls=0))
