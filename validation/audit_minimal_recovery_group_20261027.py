"""Offline audit of partial group receipts, immutable parents and unknowns."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash


def audit(root):
    registration=read(root/'registration.json');result=read(root/'result.json')
    for source in registration['sources'].values():
        for name,expected in source['sha256'].items():assert file_hash(Path(source['path'])/name)==expected
    for parent in registration['native_parents'].values():assert file_hash(parent['path'])==parent['sha256']
    receipts={};unknown=[];phases=[]
    for path in sorted(root.glob('R*/[BC]/*/phase-outcome.json')):
        phase=read(path);phases.append(dict(path=str(path),completed=phase['completed'],failure=phase.get('failure'),
            usage_complete=phase['usage_complete'],response_count=phase['receipts']['response_count']))
        if not phase['usage_complete']:unknown.append(str(path))
        for receipt in phase['receipts']['response_receipts']:
            identity=receipt['response_id'];assert identity not in receipts
            receipts[identity]=receipt['usage']
    known=sum(x['total_tokens'] for x in receipts.values());ledger=result['ledger']
    assert ledger['study']['tokens']==known and ledger['study']['responses']==len(receipts)
    assert ledger['study']['uncertain']==bool(unknown) and not ledger['inflight']
    def clean(value):
        if isinstance(value,dict):
            if 'empty_confirmed' in value:assert value['empty_confirmed']
            for child in value.values():clean(child)
        elif isinstance(value,list):
            for child in value:clean(child)
    # Every actually opened owner wrote this receipt. Undispatched C sessions
    # can have no owner; no invented clean receipt is needed in that case.
    cleanup=list(root.rglob('process-cleanup.json'))
    for path in cleanup:clean(read(path))
    for child in result.get('results',{}).values():clean(child.get('cleanup'))
    envelope=read(root/'next-admission-envelope.json');assert envelope['historical_uncertainty'] and envelope['old_unknowns_preserved']
    return dict(passed=True,model_calls=0,source_parents_unchanged=True,distinct_new_receipts=len(receipts),
        known_new_tokens=known,new_usage_unknown=bool(unknown),historical_unknown_preserved=True,
        phases=phases,cleanup_receipts_verified=len(cleanup),group_status=result['status'],
        scope='Partial receipt/accounting and immutable-source proof only, not completed three-pair quality evidence.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    value=audit(args.root);save(args.root/'group-audit.json',value)
    print(json.dumps({k:v for k,v in value.items() if k!='phases'}))
