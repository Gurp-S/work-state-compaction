"""Compact read-only status; live receipt totals are lower bounds."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read
from native_rollout_snapshot import capture_rollout

AREA=Path(sys.argv[1]) if len(sys.argv)>1 else Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1')
for arm in ('B','C'):
    output=AREA/'arms'/arm/'output'
    completed=[]
    for path in sorted(output.glob('*/phase-outcome.json')):
        phase=read(path)
        completed.append(dict(phase=path.parent.name,completed=phase['completed'],failure=phase.get('failure'),
            usage_complete=phase.get('usage_complete'),responses=phase.get('receipts',{}).get('response_count'),
            tokens=phase.get('receipts',{}).get('all_usage',{}).get('total_tokens')))
    tids=set()
    receipts={}
    for name in ('thread-start.json','thread-fork.json'):
        for path in output.glob('*/'+name):
            thread=read(path)['thread']
            if thread['id'] in tids:
                continue
            tids.add(thread['id'])
            snapshot=capture_rollout(thread['path'])
            for row in snapshot.rows:
                if row['type']=='token_usage_record':
                    value=row['payload']
                    rid=value['response_id']
                    if rid in receipts:
                        assert receipts[rid]==value['usage']
                    receipts[rid]=value['usage']
    result=read(output/'worker-result.json') if (output/'worker-result.json').exists() else None
    print(dict(arm=arm,closed_phases=completed,known_live_responses=len(receipts),
        known_live_total_tokens=sum(value['total_tokens'] for value in receipts.values()),
        terminal_state=result['state'] if result else None,error=result.get('error') if result else None),flush=True)
