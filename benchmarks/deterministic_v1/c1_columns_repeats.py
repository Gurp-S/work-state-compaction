"""Only two missing full C chains, concurrent under one admission ledger."""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,time
from c1_columns_qualification import run
from native_application_budget import StudyBudget
from native_evidence import read,save,file_hash
from blackbox_budget import close


def main():
    p=argparse.ArgumentParser()
    for name in ('source','admission','first','parent-envelope','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--execute',action='store_true');args=p.parse_args()
    if not args.execute:p.error('Explicit --execute required')
    if not read(args.first/'audit.json')['passed'] or not read(args.first/'C1-equivalence-audit.json')['passed']:raise ValueError('first_chain_not_audited')
    parent=read(args.parent_envelope);spec=dict(max_total_tokens=520000,max_responses=12,max_seconds=900)
    arms={name+'/wsc':spec for name in ('R02','R03')};caps=dict(max_total_tokens=1040000,max_responses=24,max_seconds=1000)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('campaign_allocation_insufficient')
    source_hash=file_hash(args.source/'R01/state.db');args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget(arms,caps)
    save(args.out/'registration.json',dict(id='C1_columns_missing_full_repeats/1',workers=2,arms=arms,limits=caps,first_chain=str(args.first),first_chain_audit_sha256=file_hash(args.first/'audit.json'),
        first_chain_known_at_registration=True,source=str(args.source),source_database_sha256=source_hash,automatic_retries=0,independent_C1_per_chain=True,
        historical_native_controls_reused=True,parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        code_sha256={p.name:file_hash(p) for p in [Path(__file__),Path(__file__).with_name('c1_columns_qualification.py')]}))
    results={}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending={}
            for number in (2,3):
                name=f'R{number:02d}';child=SimpleNamespace(source=args.source,admission=args.admission,parent_envelope=args.parent_envelope,out=args.out/name,execute=True)
                pending[pool.submit(run,child,ledger=ledger,repetition=number)]=name
            for future in as_completed(pending):
                name=pending[future]
                try:results[name]=future.result()
                except Exception as error:results[name]=dict(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:save(args.out/'dispatch-ledger.json',ledger.snapshot())
    unchanged=file_hash(args.source/'R01/state.db')==source_hash
    result=dict(status='completed' if unchanged and len(results)==2 and all(r['status']=='completed' for r in results.values()) else 'failed_preserved',results=results,
        ledger=ledger.snapshot(),seconds=time.monotonic()-begin,source_unchanged=unchanged,whole_campaign_usage_complete=False,prior_unknown_preserved=True)
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(dict(status=result['status'],tokens=result['ledger']['study']['tokens'],responses=result['ledger']['study']['responses']),flush=True)


if __name__=='__main__':main()
