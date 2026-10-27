"""Receipt-checked three independent C chains versus frozen historical B."""
from pathlib import Path
import argparse,csv,json,statistics,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from blackbox_group_report import paired_interval
from blackbox import score_answer
from late_recovery_case import build


def main():
    parser=argparse.ArgumentParser()
    for name in ('first','repeats','native-first','native-rest','old-report','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();group=read(args.repeats/'result.json');assert group['status']=='completed' and not group['ledger']['inflight'] and not group['ledger']['study']['uncertain']
    _,oracle,_=build();rows=[];new_receipts={};all_receipts={}
    for rep in ('R01','R02','R03'):
        croot=args.first if rep=='R01' else args.repeats/rep
        broot=(args.native_first if rep=='R01' else args.native_rest/rep)/'B'
        assert read(croot/'audit.json')['passed'] and read(croot/'C1-equivalence-audit.json')['passed']
        for arm,folder,names in [('C',croot/'R01',['C1-selection','C2-selection','wsc-probe']),('B',broot,['B1-compression','B2-compression','query'])]:
            phases=[read(folder/name/'phase-outcome.json') for name in names];receipts={}
            for phase in phases:
                assert phase['completed'] and phase['usage_complete'] and not phase['failure']
                for r in phase['receipts']['response_receipts']:
                    assert r['response_id'] not in all_receipts;all_receipts[r['response_id']]=r['usage'];receipts[r['response_id']]=r['usage']
            actual={}
            for path in folder.glob('closed-*.jsonl'):
                snap=capture_rollout(path);assert snap.metadata['parse_complete']
                for r in snap.rows:
                    if r['type']=='token_usage_record':
                        payload=r['payload'];assert payload['response_id'] not in actual;actual[payload['response_id']]=payload['usage']
            assert actual==receipts
            scored=score_answer(phases[-1]['finals'][0]['text'],oracle)
            if arm=='B':
                assert all(read(folder/(name+'-proof.json'))['confirmed'] for name in names[:2])
                assert scored==read(folder/'result.json')['scores']
                cleanup=read(folder/'result.json')['cleanup'];elapsed=read(folder/'result.json')['seconds']
            else:
                assert scored==read(croot/'result.json')['score'];cleanup=read(croot/'result.json')['cleanup']
                elapsed=read(croot/'result.json').get('exact_full_wall_seconds',read(croot/'result.json')['seconds'])
                if rep!='R01':
                    state=group['ledger']['arms'][rep+'/wsc'];assert sum(v['total_tokens'] for v in receipts.values())==state['tokens'] and len(receipts)==state['responses'];new_receipts.update(receipts)
            assert all(c['empty_confirmed'] for c in cleanup.values())
            row=dict(repetition=rep,arm=arm,correct=scored['counts']['correct'],questions=2,tokens=sum(v['total_tokens'] for v in receipts.values()),responses=len(receipts),
                phase_seconds=sum(p['seconds'] for p in phases),system_seconds=elapsed,historical_control=arm=='B',C1_reused=False,
                first_stage_tokens=phases[0]['receipts']['all_usage']['total_tokens'],first_stage_input=phases[0]['receipts']['all_usage']['input_tokens'],first_stage_seconds=phases[0]['seconds'])
            rows.append(row)
    assert set(new_receipts)==set(group['ledger']['response_ids']) and sum(v['total_tokens'] for v in new_receipts.values())==group['ledger']['study']['tokens']
    summary={}
    for arm in ('B','C'):
        selected=[r for r in rows if r['arm']==arm]
        summary[arm]=dict(correct=sum(r['correct'] for r in selected),questions=6,tokens=[r['tokens'] for r in selected],mean_tokens=statistics.mean(r['tokens'] for r in selected),
            median_tokens=statistics.median(r['tokens'] for r in selected),mean_phase_seconds=statistics.mean(r['phase_seconds'] for r in selected),
            mean_first_stage_tokens=statistics.mean(r['first_stage_tokens'] for r in selected),mean_first_stage_seconds=statistics.mean(r['first_stage_seconds'] for r in selected))
    deltas=[]
    for rep in ('R01','R02','R03'):
        c=next(r for r in rows if r['repetition']==rep and r['arm']=='C');b=next(r for r in rows if r['repetition']==rep and r['arm']=='B');deltas.append(c['tokens']-b['tokens'])
    old=read(args.old_report/'report.json');old_mean=old['summary']['C']['mean_full_chain_tokens']
    result=dict(passed=True,model_calls=0,rows=rows,summary=summary,new_known_tokens=group['ledger']['study']['tokens'],new_responses=len(new_receipts),
        C_cost_excess_vs_historical_B=summary['C']['mean_tokens']/summary['B']['mean_tokens']-1,C_cost_reduction_vs_old_C=1-summary['C']['mean_tokens']/old_mean,
        paired_token_delta=paired_interval(deltas),old_C_mean_tokens=old_mean,
        source_unchanged=group['source_unchanged'],all_new_receipts_closed=True,
        limitations=['Same single case, one recovered historical C and two new C, all B historical.','Three independent C1/C2 chains; not shared C1 and not independent tasks.','C1 R01 exact full wall unknown after recovered coordinator failure; no imputed time.','Descriptive tiny-sample bootstrap does not establish population confidence or algorithm causation.'])
    args.out.mkdir(parents=True,exist_ok=False);save(args.out/'report.json',result)
    with (args.out/'metrics.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:result[k] for k in ('summary','C_cost_excess_vs_historical_B','C_cost_reduction_vs_old_C','paired_token_delta')},indent=2))


if __name__=='__main__':main()
