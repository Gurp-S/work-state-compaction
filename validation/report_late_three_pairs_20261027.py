"""Zero-judge source/receipt audit and descriptive three-pair report."""
from pathlib import Path
from copy import deepcopy
import argparse,sys,json,csv,statistics
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_generation_binding import verify_transcript
from native_event_table import restore
from blackbox import compression_evidence,score_answer,questions
from blackbox_group_report import paired_interval
from late_recovery_case import build
from dataset import canonical
from audit_source_tool_20261027 import audit as audit_tool


def collect(args):
    reg=read(args.root/'registration.json');closed=read(args.root/'result.json')
    assert closed['status']=='completed' and not closed['ledger']['inflight'] and not closed['ledger']['study']['uncertain']
    src=Path(reg['sources']['R01']['path']);public=read(src.parent/'dataset.public.json')
    _,oracle,_=build(public['seed'],public['receipt_count'],public['target_build_number'])
    assert all(file_hash(src/n)==h for n,h in reg['sources']['R01']['sha256'].items())
    c1=read(src/'C1-selection/phase-outcome.json');all_receipts={};rows=[];audits={}
    old_c=Path(read(args.first/'registration.json')['reused_C'])
    old_request=read(old_c/'generation/request.json')
    for rep in ('R01','R02','R03'):
        rep_root=args.first if rep=='R01' else args.root/rep
        for arm in ('B','U','C'):
            folder=old_c if rep=='R01' and arm=='C' else rep_root/arm
            names=['B1-compression','B2-compression','query'] if arm=='B' else ['selection','query'] if arm=='C' else ['query']
            phases=[];receipts={}
            for name in names:
                phase=read(folder/name/'phase-outcome.json');phases.append(phase)
                assert phase['completed'] and phase['usage_complete'] and not phase['failure']
                for r in phase['receipts']['response_receipts']:
                    assert r['response_id'] not in receipts;receipts[r['response_id']]=r['usage']
                    if rep!='R01':
                        assert r['response_id'] not in all_receipts;all_receipts[r['response_id']]=r['usage']
                if name.startswith('B'):
                    raw=(folder/name/'rollout.jsonl').read_bytes();before=raw[:phase['turn_accounting']['before']['byte_length']]
                    events=[json.loads(s) for s in (folder/name/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                    proof=compression_evidence(before,raw,phase,events)
                    assert proof['confirmed'] and proof==read(folder/(name+'-proof.json'))
            assert read(folder/'query/attempt.json')['request']==canonical(questions(oracle))
            result=read(folder/'result.json');scored=score_answer(phases[-1]['finals'][0]['text'],oracle)
            assert result['status']=='completed' and result['scores']==scored
            assert all(v['empty_confirmed'] for v in result['cleanup'].values())
            actual={}
            for path in folder.glob('closed-*.jsonl'):
                snap=capture_rollout(path);assert snap.metadata['parse_complete']
                if arm=='U':assert not any(r['type']=='compacted' for r in snap.rows)
                for row in snap.rows:
                    if row['type']=='token_usage_record':
                        r=row['payload'];assert r['response_id'] not in actual;actual[r['response_id']]=r['usage']
            assert actual==receipts
            if arm=='C' and rep!='R01':
                generation=folder/'generation';phase=phases[0]
                proof,submitted=verify_transcript(capture_rollout(folder/'selection/rollout.jsonl'),phase)
                assert submitted==read(generation/'request.json') and proof==read(generation/'request-binding.json')
                a=deepcopy(old_request);b=deepcopy(submitted)
                for request,path in ((a,old_c/'generation'),(b,generation)):
                    request['material']=restore(request['material'],read(path/'event-table-binding.json'))
                    for k in ('path','sha256'):request['material']['cold_source_manifest'].pop(k)
                assert a==b and read(generation/'schema.json')==read(old_c/'generation/schema.json')
                tool=audit_tool(folder,decode_json_strings=True);assert tool['passed']
                destination=folder/'source-tool-audit.json'
                if destination.exists():assert read(destination)==tool
                else:save(destination,tool)
                audits[rep]=dict(request_equal_except_manifest_locator=True,schema_equal=True,tool_audit_passed=True)
            token=sum(v['total_tokens'] for v in receipts.values());responses=len(receipts)
            elapsed=sum(p['seconds'] for p in phases)
            row=dict(repetition=rep,arm=arm,correct=scored['counts']['correct'],questions=2,
                measured_tokens=token,measured_responses=responses,measured_phase_seconds=elapsed,
                full_chain_tokens=token+(c1['receipts']['all_usage']['total_tokens'] if arm=='C' else 0),
                full_chain_responses=responses+(c1['receipts']['response_count'] if arm=='C' else 0),
                full_chain_phase_seconds=elapsed+(c1['seconds'] if arm=='C' else 0),
                system_seconds=result.get('seconds'),C1_reused=arm=='C',historical=rep=='R01')
            if rep!='R01':
                ledger=closed['ledger']['arms'][rep+'/'+arm]
                assert token==ledger['tokens'] and responses==ledger['responses']
            rows.append(row)
    assert set(all_receipts)==set(closed['ledger']['response_ids'])
    assert sum(v['total_tokens'] for v in all_receipts.values())==closed['ledger']['study']['tokens']
    summary={}
    for arm in ('B','U','C'):
        arm_rows=[r for r in rows if r['arm']==arm]
        summary[arm]=dict(correct=sum(r['correct'] for r in arm_rows),questions=6,
            mean_full_chain_tokens=statistics.mean(r['full_chain_tokens'] for r in arm_rows),
            mean_phase_seconds=statistics.mean(r['full_chain_phase_seconds'] for r in arm_rows),
            observed_correct_distribution=[r['correct'] for r in arm_rows])
    deltas=[]
    for rep in ('R01','R02','R03'):
        b=next(r for r in rows if r['repetition']==rep and r['arm']=='B');c=next(r for r in rows if r['repetition']==rep and r['arm']=='C')
        deltas.append((c['correct']-b['correct'])/2)
    result=dict(passed=True,model_calls=0,rows=rows,summary=summary,source_unchanged=True,unique_new_receipts=len(all_receipts),
        new_tokens=closed['ledger']['study']['tokens'],C_request_audits=audits,paired_accuracy_delta=paired_interval(deltas),
        scope='Three same-case system repetitions, shared C1 and historical R01. Descriptive bootstrap only; not independent tasks, not causal latency or whole-WSC proof.')
    args.out.mkdir(parents=True,exist_ok=False);save(args.out/'report.json',result)
    with (args.out/'metrics.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps(dict(summary=summary,paired_accuracy_delta=result['paired_accuracy_delta'],new_tokens=result['new_tokens']),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','first','out'):p.add_argument('--'+name,type=Path,required=True)
    collect(p.parse_args())
