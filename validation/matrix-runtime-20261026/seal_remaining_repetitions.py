"""Bind the explicit execution-time choice and live quota before dispatch."""
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,digest
from native_host_controls import settings
from native_owned_process import OwnedNativeRPC
from native_application_session import NativeApplicationSession
COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
OUT=Path('D:/agent-task-runs/wsc-remaining-repetitions-admission-20261027-v1')
OUT.mkdir(exist_ok=False)
spec=read(COHORT/'registration.json')
for arm in ('B','C'):
    reg=spec['sessions'][arm]
    check=NativeApplicationSession(reg,OUT/('source-check-'+arm))
    assert check.source_manifest()==reg['initial_manifest'],'remaining_repetition_not_S2'
reg=spec['sessions']['B']
server=None
begin=time.monotonic()
quota=dict(model_calls=0)
try:
    server=OwnedNativeRPC(reg['executable'],cwd=OUT,stderr_path=OUT/'quota-stderr.txt',settings=settings(reg))
    server.call('initialize',dict(clientInfo=dict(name='remaining_repetitions_admission',version='1'),capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    limits=server.call('account/rateLimits/read',{})['rateLimits']
    quota['primary']=limits.get('primary');quota['secondary']=limits.get('secondary')
    quota['available_observed']=all(isinstance(quota[k],dict) and 0<=quota[k].get('usedPercent',100)<100 for k in ('primary','secondary')) and limits.get('rateLimitReachedType') is None
finally:
    quota['cleanup']=server.close() if server else dict(empty_confirmed=True,process_started=False)
    quota['seconds']=time.monotonic()-begin
    save(OUT/'quota-readback.json',quota)
assert quota['available_observed'] and quota['cleanup']['empty_confirmed']
operations=[quota['seconds']]
for folder,name in [('D:/agent-task-runs/wsc-repeat-admission-review-20261027-v1','quota-readback.json'),
                    ('D:/agent-task-runs/wsc-scope-locator-review-20261027-v1','result.json')]:
    path=Path(folder)
    operations.append(max(0,(path/name).stat().st_mtime-path.stat().st_ctime))
prior=COHORT/'execution-v2/R03/next-admission-envelope.json'
diagnostic=Path('D:/agent-task-runs/wsc-scope-locator-review-20261027-v1/scoped-control-and-center-check.mjs')
adoption=dict(user_choice='按实际实验运行时间累计，额度等待不计（推荐）',
    policy='recorded_execution_wall_only_v1',parent_envelope_sha256=file_hash(prior),
    new_completed_operation_seconds=operations,prior_closed_remaining_limits=read(prior)['remaining_limits'],
    closed_calendar_gap_seconds=time.time()-prior.stat().st_mtime,quota_wait_not_charged=True,
    hard_caps_increased=False,old_failures_and_unknowns_preserved=True,quota_readback=str(OUT/'quota-readback.json'),
    quota_readback_sha256=file_hash(OUT/'quota-readback.json'),scope_diagnostic_path=str(diagnostic),
    scope_diagnostic_sha256=file_hash(diagnostic),original_primary_grading_unchanged=True,
    remaining_repetitions=[2,3],original_pair_1_not_retried=True)
save(COHORT/'execution-time-policy-adoption.json',adoption)
save(OUT/'result.json',dict(admission_ready=True,source_S2_equal=True,model_calls=0,
    adoption_sha256=file_hash(COHORT/'execution-time-policy-adoption.json')))
print(dict(admission_ready=True,model_calls=0,operation_seconds=sum(operations),quota_primary=quota['primary']['usedPercent']))
