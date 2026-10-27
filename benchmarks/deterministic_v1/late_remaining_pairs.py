"""Complete R02/R03 conditional-C1 repeats, retaining historical R01.

Only scheduling changes: unchanged native counterpart and C candidate workers.
"""
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,time,sqlite3
from late_native_counterpart import run_arm
from qualify_source_tool import run_candidate,PROFILE,ROOT
from native_evidence import read,save,file_hash
from native_application_budget import StudyBudget
from native_latency import LatencyRecorder,summarize
from blackbox_budget import close as close_budget
from late_recovery_case import build
from blackbox import questions
from dataset import seal,canonical


class ArmLedger:
    """Map existing worker-local names to globally unique ledger arms."""
    def __init__(self,ledger,prefix):self.ledger,self.prefix=ledger,prefix
    def reserve(self,arm,limits):return self.ledger.reserve(self.prefix+'/'+arm,limits)
    def mark_unknown(self,arm,*args):return self.ledger.mark_unknown(self.prefix+'/'+arm,*args)
    def settle(self,*args):return self.ledger.settle(*args)


def run(args):
    source=args.source/'R01';public=read(args.source/'dataset.public.json')
    rebuilt,_,_=build(public['seed'],public['receipt_count'],public['target_build_number'])
    if public!=rebuilt:raise ValueError('source_public_changed')
    first=read(args.first/'independent-audit.json')
    if not first['passed'] or first['native_compactions_confirmed']!=2:raise ValueError('first_pair_not_audited')
    gate=read(args.codec_admission/'result.json')
    if not gate['passed'] or gate['model_calls']!=0 or gate['codec_sha256']!=file_hash(ROOT/'experiments/native_event_table.py') or gate['source_database_sha256']!=file_hash(source/'state.db'):raise ValueError('codec_admission_changed')
    if not read(args.source/'audit.json')['passed']:raise ValueError('source_not_audited')
    with sqlite3.connect(source/'state.db') as db:
        if db.execute('SELECT count(*) FROM understandings').fetchone()[0]!=0:raise ValueError('prior_M_leak')
    names=['state.db','result.json','C1-continuation.json','C1-selection/phase-outcome.json','parent-session/thread-fork.json','parent-session/ancestry/binding.json']
    frozen={name:file_hash(source/name) for name in names}
    query=dict(max_total_tokens=120000,max_responses=4,max_seconds=120)
    specs={'B':dict(max_total_tokens=520000,max_responses=12,max_seconds=600),'U':query,'C':dict(max_total_tokens=320000,max_responses=8,max_seconds=360)}
    arms={rep+'/'+arm:spec for rep in ('R02','R03') for arm,spec in specs.items()}
    caps=dict(max_total_tokens=sum(x['max_total_tokens'] for x in arms.values()),max_responses=sum(x['max_responses'] for x in arms.values()),max_seconds=1000)
    parent=read(args.parent_envelope)
    if any(caps[k]>parent['remaining_limits'][k] for k in caps):raise ValueError('campaign_allocation_insufficient')
    args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic();ledger=StudyBudget(arms,caps)
    registration=dict(id='late-remaining-pairs/1',dataset_type='late-recovery/1',sources={'R01':dict(path=str(source.resolve()),sha256=frozen)},
        arm_limits=arms,query_limits=query,limits=caps,service_check_on_selector=True,service_ready=False,
        first_pair=str(args.first),first_pair_audit_sha256=file_hash(args.first/'independent-audit.json'),
        shared_C1=True,repeated_unit='C2 plus query conditional on fixed C1; B independently repeats both native compactions.',
        historical_R01=True,workers=3,order=['R02:B,U,C','R03:C,U,B'],automatic_retries=0,
        C_initial_artifacts='fresh cold-public/cold-objects for each new C; matching prior C2 qualification. OS/cache state uncontrolled, measured only.',
        latency_causation_claim=False,public_sha256=seal(public),
        parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope),
        code_sha256={str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),Path(__file__).with_name('late_native_counterpart.py'),Path(__file__).with_name('qualify_source_tool.py')]})
    save(args.out/'registration.json',registration)
    base=read(source/'parent-session/registration.json');save(args.out/'model-registration.json',dict(sessions={'B':base}))
    def worker(rep,arm):
        folder=args.out/rep
        if arm!='C':
            local=SimpleNamespace(out=folder,source=args.source,execute=args.execute)
            _,oracle,_=build(public['seed'],public['receipt_count'],public['target_build_number'])
            return run_arm(arm,local,registration,oracle,ArmLedger(ledger,rep))
        if not args.execute:return dict(status='admission_passed',model_calls=0)
        candidate=SimpleNamespace(source=source,registration=args.out/'model-registration.json',admission=args.source_tool_admission,
            parent_envelope=args.parent_envelope,out=folder/'C',selector_runtime=PROFILE,budget_tool_results=True,
            snapshot_literal_search=True,cold_event_table=True,bound_windows_io=True)
        with LatencyRecorder(folder/'C-timing.jsonl') as timing:
            result=run_candidate(candidate,ledger=ledger,arm=rep+'/C',cohort=registration,timing=timing)
        save(folder/'C-timing-summary.json',summarize(folder/'C-timing.jsonl'))
        return result
    results={}
    for rep,order in [('R02',('B','U','C')),('R03',('C','U','B'))]:
        if ledger.snapshot()['study']['uncertain']:break
        (args.out/rep).mkdir()
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending={pool.submit(worker,rep,arm):rep+'/'+arm for arm in order}
            for future in as_completed(pending):
                key=pending[future]
                try:results[key]=future.result()
                except Exception as error:results[key]=dict(status='failed_preserved',error=type(error).__name__+':'+str(error))
                print(canonical(dict(slot=key,status=results[key]['status'],error=results[key].get('error'))),flush=True)
    unchanged=all(file_hash(source/name)==h for name,h in frozen.items())
    result=dict(status='completed' if unchanged and len(results)==6 and all(v['status'] in ('completed','admission_passed') for v in results.values()) else 'failed_preserved',
        results=results,source_unchanged=unchanged,ledger=ledger.snapshot(),seconds=time.monotonic()-begin,
        prior_unknown_preserved=True,whole_campaign_usage_complete=False)
    save(args.out/'result.json',result)
    if not result['ledger']['inflight']:save(args.out/'next-admission-envelope.json',dict(**close_budget(parent,result['ledger'],result['seconds']),parent_envelope=str(args.parent_envelope),parent_envelope_sha256=file_hash(args.parent_envelope)))
    print(canonical(dict(status=result['status'],new_tokens=result['ledger']['study']['tokens'],new_responses=result['ledger']['study']['responses'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('source','first','codec-admission','source-tool-admission','parent-envelope','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--execute',action='store_true');run(parser.parse_args())
