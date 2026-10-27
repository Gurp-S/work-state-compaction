"""Append an independent lifecycle audit; never rewrite registered results."""
from pathlib import Path
from hashlib import sha256
import collections
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_cleanup_terminal import observe

PAIR=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1/execution-v3/R02')
OUT=Path('D:/agent-task-runs/wsc-R02-terminal-review-20261027-v1')
OUT.mkdir(exist_ok=False)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
hashfile=lambda p:sha256(p.read_bytes()).hexdigest()
report=dict(model_calls=0,original_records_unchanged=True,arms={})
for arm in ('B','C'):
    folder=PAIR/arm
    phase=folder/'S3-phase'
    paths=[phase/'phase-outcome.json',phase/'events.jsonl',phase/'rollout.jsonl',
           folder/'result.json',folder/'qualification.json']
    hashes={str(p):hashfile(p) for p in paths}
    old=read(paths[0])
    before=dict(completed=old['completed'],failure=old['failure'])
    after=dict(before)
    turn_id=old['turn_accounting']['turn_id']
    statuses=[]
    for line in (phase/'events.jsonl').read_text(encoding='utf-8').splitlines():
        event=json.loads(line)
        if event.get('method')=='turn/completed' and observe(after,event['params'],thread_id=old['thread_id'],turn_id=turn_id):
            statuses.append(after['native_terminal_status'])
    assert len(statuses)==1
    rows=[json.loads(line) for line in (phase/'rollout.jsonl').read_text(encoding='utf-8').splitlines()]
    terminal=[dict(line=i+1,type=row['payload']['type']) for i,row in enumerate(rows)
              if row.get('type')=='event_msg' and row.get('payload',{}).get('type') in ('task_complete','turn_aborted')]
    assert [x['type'] for x in terminal]==(['task_complete'] if arm=='C' else ['turn_aborted'])
    assert after['completed']==(arm=='C')
    assert after['failure']==before['failure']=='registered_token_cap'
    usage=old['receipts']['all_usage']
    assert usage['total_tokens']>6000000
    assert old['usage_complete']==(arm=='C')
    report['arms'][arm]=dict(source_hashes=hashes,before=before,derived_after=after,
        terminal_source=terminal,final_messages=len(old['finals']),
        usage_complete=old['usage_complete'],usage=usage,responses=old['receipts']['response_count'],
        seconds=old['seconds'],automatic_compactions=sum(row['type']=='compacted' for row in rows),
        token_cap=6000000,known_cap_overshoot=usage['total_tokens']-6000000,
        qualification=read(folder/'qualification.json'),
        accounted_reasons=old['turn_accounting']['reasons'])
    assert all(hashfile(p)==hashes[str(p)] for p in paths)
report['next_repetition_admission']=read(PAIR/'next-repetition-admission.json')
assert report['next_repetition_admission']['admitted'] is False
report['conclusion']='Both functional checks pass; both exceed cap. C completed, B interrupted with unknown full usage. R03 not admitted.'
with (OUT/'audit.json').open('x',encoding='utf-8') as stream:
    json.dump(report,stream,ensure_ascii=False,indent=2)
print(json.dumps(dict(model_calls=0,completed={a:r['derived_after']['completed'] for a,r in report['arms'].items()},original_records_unchanged=True),ensure_ascii=False))
