"""Replay old failures and read current quota without an inference request."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from native_repeat_admission import decide
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
OUT=Path('D:/agent-task-runs/wsc-repeat-admission-review-20261027-v1')
OUT.mkdir(exist_ok=False)
replay=[]
for label in ('R01','R02','R03'):
    area=COHORT/'execution-v2'/label
    pair=read(area/'pair-result.json')
    phase={arm:read(area/arm/'phase-journal.json') for arm in ('B','C')}
    decision=decide(pair['results'],phase,pair['ledger'])
    assert not decision['admitted']
    replay.append(dict(pair=label,decision=decision,pair_receipt_sha256=file_hash(area/'pair-result.json')))
save(OUT/'historical-replay.json',dict(before_dispatched_pairs=3,after_would_dispatch_pairs=1,
    prevented_later_turn_start_requests=4,replay=replay,model_calls=0,
    savings_claim='No inference-token savings asserted; old later rejections have zero known receipts and unknown completeness'))
reg=read(COHORT/'registration.json')['sessions']['B']
server=None
result=dict(model_calls=0,turn_started=False)
try:
    server=OwnedNativeRPC(reg['executable'],cwd=OUT,stderr_path=OUT/'quota-stderr.txt',settings=settings(reg))
    server.call('initialize',dict(clientInfo=dict(name='quota_readback',version='1'),capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    value=server.call('account/rateLimits/read',{})
    limits=value.get('rateLimits',{})
    result['rate_limits']=limits
    windows=[limits.get(name) for name in ('primary','secondary')]
    result['available_observed']=bool(windows and all(isinstance(w,dict) and type(w.get('usedPercent')) in (int,float)
        and 0<=w['usedPercent']<100 for w in windows) and limits.get('rateLimitReachedType') is None)
except Exception as error:result['error']=type(error).__name__+':'+str(error)
finally:
    result['cleanup']=server.close() if server else dict(empty_confirmed=True,process_started=False)
    save(OUT/'quota-readback.json',result)
print(result)
