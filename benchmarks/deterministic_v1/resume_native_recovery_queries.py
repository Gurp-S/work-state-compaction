"""Only the two missing B queries, equal registered four-response QA budget."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,time
from blackbox_minimal_recovery_group import native_query,probe_service
from native_application_budget import StudyBudget
from native_evidence import read,save,file_hash
from blackbox_budget import close as close_budget
from blackbox import questions
from dataset import seal


def main():
    parser=argparse.ArgumentParser()
    for name in ('group','r01-c','r03-c','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:parser.error('Explicit --execute required')
    begin=time.monotonic();original=read(args.group/'registration.json');prior=read(args.group/'result.json')
    c1=read(args.r01_c/'result.json');c3=read(args.r03_c/'result.json')
    if c1['status']!='completed' or c3['status']!='completed':raise ValueError('C_continuations_not_completed')
    if prior['results']['R03/B']['status']!='completed':raise ValueError('native_R03_not_reusable')
    oracle=read(Path(read(args.r03_c/'registration.json')['source'])/'oracle.private.json')
    if oracle['public_sha256']!=original['public_sha256'] or seal(questions(oracle))!=original['query_sha256']:raise ValueError('query_or_oracle_changed')
    for record in original['sources'].values():
        for name,checksum in record['sha256'].items():
            if file_hash(Path(record['path'])/name)!=checksum:raise ValueError('frozen_source_changed')
    for parent in original['native_parents'].values():
        if file_hash(parent['path'])!=parent['sha256']:raise ValueError('frozen_native_parent_changed')
    qa=dict(max_total_tokens=120000,max_responses=4,max_seconds=120)
    caps=dict(max_total_tokens=240000,max_responses=8,max_seconds=300);parent=read(args.parent_envelope)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('parent_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);ledger=StudyBudget({name+'/native':qa for name in ('R01','R02')},caps)
    save(args.out/'registration.json',dict(source_group=str(args.group),source_group_registration_sha256=file_hash(args.group/'registration.json'),
        source_group_result_sha256=file_hash(args.group/'result.json'),query_limits=qa,limits=caps,
        completed_C=dict(R01=str(args.r01_c),R02=original['reuse']['path'],R03=str(args.r03_c)),
        old_interrupted_queries_retained=True,query_from_original_B2_parents=True,automatic_retries=0,
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    ready=probe_service(original['native_parents']['R01']['registration'],args.out/'service-readiness')
    results={'R03':prior['results']['R03/B']};status='readiness_failed'
    if ready['passed']:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending={pool.submit(native_query,name,original['native_parents'][name],oracle,args,ledger,qa):name for name in ('R01','R02')}
            for future in as_completed(pending):
                name=pending[future]
                try:results[name]=future.result()
                except Exception as error:results[name]=dict(status='failed_preserved',error=str(error))
                print(name,results[name]['status'],results[name].get('scores'),flush=True)
        status='completed' if len(results)==3 and all(r['status']=='completed' for r in results.values()) else 'failed_preserved'
    result=dict(status=status,results=results,ledger=ledger.snapshot(),seconds=time.monotonic()-begin,readiness=ready,old_unknowns_preserved=True)
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(status,result['ledger']['study'])


if __name__=='__main__':main()
