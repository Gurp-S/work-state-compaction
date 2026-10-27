"""Read-only deterministic audit of the first late native counterpart."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash
from blackbox import compression_evidence,score_answer,questions
from dataset import canonical
from native_rollout_snapshot import capture_rollout
from late_recovery_case import build


def audit(root):
    registration=read(root/'registration.json');result=read(root/'result.json')
    source=Path(registration['reused_C']).parent
    old_source=Path(read(Path(registration['reused_C'])/'registration.json')['source']).parent
    public=read(old_source/'dataset.public.json');_,oracle,_=build(public['seed'],public['receipt_count'],public['target_build_number'])
    assert result['status']=='completed' and not result['ledger']['inflight'] and not result['ledger']['study']['uncertain']
    assert all(file_hash(Path(p))==h for p,h in registration['source_sha256'].items())
    receipts={};metrics={};scores={}
    for arm,names in [('B',['B1-compression','B2-compression','query']),('U',['query'])]:
        rows=[];tokens=responses=0;seconds=0.
        for name in names:
            folder=root/arm/name;phase=read(folder/'phase-outcome.json')
            assert phase['completed'] and not phase['failure'] and phase['usage_complete']
            for receipt in phase['receipts']['response_receipts']:
                assert receipt['response_id'] not in receipts
                receipts[receipt['response_id']]=receipt['usage'];tokens+=receipt['usage']['total_tokens'];responses+=1
            seconds+=phase['seconds']
            if name!='query':
                raw=(folder/'rollout.jsonl').read_bytes();length=phase['turn_accounting']['before']['byte_length']
                events=[json.loads(s) for s in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
                actual=compression_evidence(raw[:length],raw,phase,events)
                assert actual==read(root/arm/(name+'-proof.json')) and actual['confirmed']
            else:
                assert read(folder/'attempt.json')['request']==canonical(questions(oracle))
                scores[arm]=score_answer(phase['finals'][0]['text'],oracle)
                assert scores[arm]==result['results'][arm]['scores']
        for name in ('history','probe'):
            snap=capture_rollout(root/arm/('closed-'+name+'.jsonl'))
            assert snap.metadata['parse_complete']
            local=[r for r in snap.rows if r['type']=='token_usage_record']
            rows.extend(local)
            if arm=='U':assert not any(r['type']=='compacted' for r in snap.rows)
        assert {r['payload']['response_id']:r['payload']['usage'] for r in rows}=={rid:usage for rid,usage in receipts.items() if rid in {r['payload']['response_id'] for r in rows}}
        assert sum(r['payload']['usage']['total_tokens'] for r in rows)==tokens
        assert len(rows)==responses and len({r['payload']['response_id'] for r in rows})==responses
        assert all(x['empty_confirmed'] for x in result['results'][arm]['cleanup'].values())
        assert tokens==result['ledger']['arms'][arm]['tokens'] and responses==result['ledger']['arms'][arm]['responses']
        metrics[arm]=dict(tokens=tokens,responses=responses,phase_seconds=seconds,system_seconds=result['results'][arm]['seconds'])
    assert set(receipts)==set(result['ledger']['response_ids'])
    assert sum(x['total_tokens'] for x in receipts.values())==result['ledger']['study']['tokens']
    candidate=Path(registration['reused_C']);assert read(candidate/'source-tool-audit.json')['passed'] and read(source/'table-run-audit.json')['passed']
    scores['C']=score_answer(read(candidate/'query/phase-outcome.json')['finals'][0]['text'],oracle)
    assert scores['C']==result['reused_C_scores']
    cphases=[read(old_source/'R01/C1-selection/phase-outcome.json'),read(candidate/'selection/phase-outcome.json'),read(candidate/'query/phase-outcome.json')]
    metrics['C']=dict(tokens=sum(p['receipts']['all_usage']['total_tokens'] for p in cphases),responses=sum(p['receipts']['response_count'] for p in cphases),phase_seconds=sum(p['seconds'] for p in cphases),system_seconds=None,system_seconds_reason='C1 reused; actual C2-only wall 95.406 cannot be called full-chain or matched current B timing.')
    value=dict(passed=True,model_calls=0,receipt_count=len(receipts),new_tokens=result['ledger']['study']['tokens'],metrics=metrics,scores=scores,
        native_compactions_confirmed=2,uncompressed_local_compactions=0,source_unchanged=True,all_cleanup_confirmed=True,
        limitations=['One case, mixed historical/prospective result; not three independent repeats.','C1 reused and C timing is historical, no whole-chain paired wall-time claim.','Model identity/effort/executable held; internal compactor parameters and queue/cache/network uncontrolled.','Reads structured boundaries and receipts, does not inspect encrypted summaries.'])
    destination=root/'independent-audit.json'
    if destination.exists():assert read(destination)==value, 'audit_result_changed'
    else:save(destination,value)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':audit(Path(sys.argv[1]))
