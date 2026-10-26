"""Inspect quota and grade the closed S2 source without model inference."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save
from native_application_adapters import FrozenApplicationAdapters
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings

AREA=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
AREA.mkdir(exist_ok=False)
PRIOR=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v3')
reg=read(PRIOR/'registration.json')
result=read(PRIOR/'result.json')
assert not result['ledger']['inflight']
assert all(row['empty_confirmed'] for worker in result['outcomes'].values() for row in worker['cleanup'])
server=OwnedNativeRPC(reg['conditions']['executable']['path'],cwd=AREA,stderr_path=AREA/'quota-stderr.txt',
    settings=settings(dict(effort=reg['conditions']['effort'],host_feature_overrides=reg['conditions']['host_feature_overrides'])))
try:
    server.call('initialize',dict(clientInfo=dict(name='wsc_prefix_quota',version='1'),capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    limits=server.call('account/rateLimits/read',{})
    save(AREA/'rate-limits.json',limits)
    print('quota',limits,flush=True)
finally:
    save(AREA/'quota-cleanup.json',server.close())
job=next(job for job in reg['jobs'] if job['arm']=='B')
adapters=FrozenApplicationAdapters(reg['conditions'],reg['tasks'],reg['expected_checks'],node_executable=reg['node_executable'])
grade=adapters.grade(job,2,AREA/'S2-source-acceptance')
save(AREA/'S2-grade.json',grade)
print(dict(checks=[dict(id=row['id'],passed=row['passed']) for row in grade['observations']],
    model_calls=0,scope='Interrupted S2 source, not completed native S2 turn'),flush=True)
