"""Prepare exact reviewed incremental package for bounded C S3; zero inference."""
from pathlib import Path
import sys,shutil,sqlite3
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,manifest
from native_fixture_transport import attach
from native_application_session import NativeApplicationSession
from native_scoped_selection_state import load
from native_visual_source_observation import from_probe
from wsc import WSC,Store
from wsc.publication import check_evidence
OUT=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
PRIOR=Path('D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1')
SELECT=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OLD=Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
def prepare():
    assert read(PRIOR/'semantic-review.json')['semantic_selection_gate_passed']
    assert read(PRIOR/'result.json')['cleanup']['empty_confirmed']
    assert not read(PRIOR/'result.json')['ledger']['inflight']
    reg=read(PRIOR/'registration.json')['session']
    work=Path(reg['workspace'])
    # Registration-only source measurement, without creating a native session.
    probe_session=object.__new__(NativeApplicationSession);probe_session.registration=reg
    assert probe_session.source_manifest()==reg['initial_manifest']==read(COMMON/'staged/capsule.json')['source_manifest']
    actual=from_probe(work/'gui',SELECT/'S2-clipping-check/registration.json',SELECT/'S2-clipping-check/result.json')
    assert actual==read(SELECT/'current-visual-observation.json')
    load(read(PRIOR/'registration.json')['scoped_state'],receiving_workspace=work)
    OUT.mkdir(exist_ok=False)
    payload=read(COMMON/'staged/payload-C.json')
    oldreg=read(OLD/'registration.json')['session']
    browser_source=Path(oldreg['browser_probe']);browser_target=work/'.wsc-runtime/browser-capability.mjs'
    assert file_hash(browser_source)==oldreg['browser_probe_sha256']
    if not browser_target.exists():shutil.copyfile(browser_source,browser_target)
    assert file_hash(browser_target)==oldreg['browser_probe_sha256']
    assert (work/'gui/node_modules').is_dir() and (work/'.wsc-runtime/browsers').is_dir()
    reg={**reg,'sandbox':'workspace-write','parent_thread_id':payload['common_prefix']['reset_parent_thread_id'],
         'parent_paths':payload['registration']['parent_paths'],'before_turn_id':payload['common_prefix']['reset_before_turn_id'],
         'browser_probe':str(browser_target),'browser_probe_sha256':file_hash(browser_target)}
    frozen=read(read(COMMON/'registration.json')['tasks']['a3']['binding'])['workspace']
    reg=attach(reg,frozen)
    source=sqlite3.connect('file:'+str(PRIOR/'state.db')+'?mode=ro',uri=True)
    target=sqlite3.connect(OUT/'state.db');source.backup(target);source.close();target.close()
    core=WSC(Store(OUT/'state.db',session_id='a3/scoped-selection-v1/C',workspace=str(work)),access=lambda *args:True)
    package=read(PRIOR/'package.json');check_evidence(core,package)
    assert package['binding']['workspace']==str(work)
    shutil.copyfile(PRIOR/'package.json',OUT/'package.json')
    save(OUT/'prepared.json',dict(registration=reg,request=payload['stages'][2]['request'],
        package=str(OUT/'package.json'),package_sha256=file_hash(OUT/'package.json'),
        original_draft=str(PRIOR/'generation/compiled-draft.json'),original_draft_sha256=file_hash(PRIOR/'generation/compiled-draft.json'),
        source_review=str(PRIOR/'semantic-review.json'),source_review_sha256=file_hash(PRIOR/'semantic-review.json'),
        source_package_unchanged=True,source_workspace_reused=True,model_calls=0,
        scope='Reviewed incremental package and exact frozen S2; runtime reused without copying dependencies'))
    save(OUT/'policy-adoption.json',dict(user_choice='采用共享剩余时间（推荐）',ordinary_time_seconds=2700,
        arm_time_seconds=2700,arm_tokens=6000000,arm_responses=120,historical_unknowns_preserved=True,old_failed_ledger_resumed=False))
    print(dict(prepared=True,package_unchanged=True,model_calls=0),flush=True)
if __name__=='__main__':prepare()
