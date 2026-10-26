"""Pre-register three paired continuations, preserving all historical expense."""
from pathlib import Path
from contextlib import closing
import sqlite3
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,digest
from native_s2_workspace_restore import restore
from native_host_controls import settings

OUT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
OUT.mkdir(exist_ok=False)
PRIOR=Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
FROZEN=COMMON/'staged/frozen-workspace'
prepared=read(PRIOR/'prepared.json')
assert read(PRIOR/'closed-review.json')['qualification_passed'] and read(PRIOR/'result.json')['cleanup']['empty_confirmed']
sessions={}
base=prepared['registration']
for arm in ('B','C'):
    work=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')/arm/'workspace'
    reg={**base,'workspace':str(work),'study_arm':arm,'browser_cache':str(work/'.wsc-runtime/browsers'),
        'browser_probe':str(work/'.wsc-runtime/browser-capability.mjs'),
        'fixture_root':str(work/'.wsc-runtime/evaluation-host-v1')}
    if arm=='B':
        reg.pop('native_c_auto_compaction',None)
        reg.pop('before_turn_id',None) # B inherits full native S2 before native compaction.
    restore(reg,FROZEN,OUT/('preserved-before-'+arm),
        expected_current=read(PRIOR/'result.json')['source_manifest_after'] if arm=='C' else reg['initial_manifest'])
    assert not any(v.startswith('model_auto_compact_token_limit=') for v in settings(reg)) if arm=='B' else settings(reg)[-1]=='model_auto_compact_token_limit=96000'
    sessions[arm]=reg
assert sessions['B']['initial_manifest']==sessions['C']['initial_manifest']
database=Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1/state.db')
with closing(sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)) as db:
    events=[json.loads(row[0]) for row in db.execute('SELECT data FROM events ORDER BY seq')]
extra=[r for r in events if r['kind']=='observation' and not r['id'].startswith('native-media:')]
assert len(extra)==6
bundle=dict(kind='historical_shared_S2_observation_material_v1',sources=[dict(source_id=r['id'],
    observed_at=r.get('observed_at'),payload=r['payload']) for r in extra],generated_WSC_understandings_included=False)
save(OUT/'shared-raw-observations.json',bundle)
package=read(PRIOR/'package.json')
save(OUT/'C-package.json',package)
assert file_hash(OUT/'C-package.json')==prepared['package_sha256']
save(OUT/'registration.json',dict(kind='fixed_S2_repeated_continuation_v1',repetitions=3,
    parallelism='B and C concurrent, repetitions sequential with exact source restore',sessions=sessions,
    request=prepared['request'],source_state='same shared S2 code and native business history',
    B_seed='One unchanged native S2 compaction after all six raw observations; fixed for continuation repetitions',
    C_seed='Existing sealed calibrated WSC package; no regeneration',
    common_raw_observations_sha256=file_hash(OUT/'shared-raw-observations.json'),
    raw_observation_source_ids=[r['id'] for r in extra],raw_observation_payloads_sha256=digest([r['payload'] for r in extra]),
    original_WSC_source_db_sha256=file_hash(database),package_sha256=file_hash(OUT/'C-package.json'),
    runtime_differences=['native S2 compaction vs WSC selected projection','C native internal threshold96000 vs B default'],
    scope='Fixed compressed-start continuation variance only; not summary-generation variance or five full application tasks',
    generation_cost_reporting='Record once-only setup separately from each continuation; no zero-cost whole-pipeline claim',
    per_arm_limits=dict(max_total_tokens=6000000,max_responses=120,max_seconds=2700),
    old_failures_and_unknowns_preserved=True,budget_parent=str(PRIOR/'post-review-admission-envelope.json'),
    automatic_retries=0,grader_policy='same 11 cumulative + 6 supplemental + production-panel scrolling',
    all_trials_must_be_reported=True,not_sufficient_for_WSC_semantic_attribution=True,
    next_step='Native B seed compaction; no continuation until both fixed-start imports and accounting are admitted'))
print(dict(prepared=True,repetitions=3,source_restored_both=True,shared_observations=6,model_calls=0))
