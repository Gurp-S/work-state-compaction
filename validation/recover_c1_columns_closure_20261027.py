"""Receipt-only closure after the recorded post-model coordinator TypeError."""
from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_latency import summarize
from late_recovery_case import build
from blackbox_budget import close


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();root=args.root
    registration=read(root/'registration.json');cell=read(root/'R01/result.json');assert cell['status']=='completed'
    assert all(v['empty_confirmed'] for v in cell['cleanup'].values())
    bootstrap=read(root/'bootstrap-session/process-cleanup.json');assert bootstrap['empty_confirmed']
    expected={};phases=[]
    for name in ('C1-selection','C2-selection','wsc-probe'):
        phase=read(root/'R01'/name/'phase-outcome.json');settlement=read(root/'R01'/(name+'-settlement.json'))
        assert phase['completed'] and phase['usage_complete'] and not phase['failure']
        assert settlement['usage_complete'] and not settlement['study_unknown'] and not settlement['observed_overshoot']
        phases.append(phase)
        for receipt in phase['receipts']['response_receipts']:
            assert receipt['response_id'] not in expected;expected[receipt['response_id']]=receipt['usage']
    actual={}
    for path in (root/'R01').glob('closed-*.jsonl'):
        snap=capture_rollout(path);assert snap.metadata['parse_complete']
        for row in snap.rows:
            if row['type']=='token_usage_record':
                r=row['payload'];assert r['response_id'] not in actual;actual[r['response_id']]=r['usage']
    assert actual==expected
    snap=capture_rollout(read(root/'bootstrap-session/opened.json')['thread']['path'])
    assert snap.metadata['parse_complete'] and not any(r['type']=='token_usage_record' for r in snap.rows)
    summary=summarize(root/'timing.jsonl')
    import json
    raw=[json.loads(s) for s in (root/'timing.jsonl').read_text().splitlines()]
    spans=[s for s in raw if s['type']=='span'];header=raw[0]
    elapsed=(max(s['end_ns'] for s in spans)-header['monotonic_ns'])/1e9
    stages=[s for s in spans if s['label']=='stage.execute_and_account']
    assert len(stages)==3
    tokens=sum(u['total_tokens'] for u in expected.values());count=len(expected);caps=registration['limits']
    state=dict(limits=caps,tokens=tokens,responses=count,started=min(s['start_ns'] for s in stages)/1e9,
        seconds=sum(s['end_ns']-s['start_ns'] for s in stages)/1e9,peer_wait_seconds=0.,stopped=False)
    ledger=dict(arms={'R01/wsc':state},study=dict(limits=caps,tokens=tokens,responses=count,uncertain=False),
        inflight={},response_ids=sorted(expected),cash=None,scope='Recovered from complete unique phase receipts and closed rollouts; started/seconds derived from host spans, not the lost in-memory ledger.')
    failure=dict(status='coordinator_failed_after_model_execution',error="TypeError: 'dict' object is not callable",location='timing.call received boot.close() instead of boot.close',
        retrospective_record=True,model_phases_completed=True,original_process_exit_code=1,model_rerun=False,exact_failure_wall_time=None)
    save(root/'execution-failure.json',failure);save(root/'bootstrap-cleanup.json',bootstrap);save(root/'timing-summary.json',summary)
    public,oracle,_=build();assert public==read(root/'dataset.public.json');save(root/'oracle.private.json',oracle)
    result={**cell,'ledger':ledger,'seconds':elapsed,'recovered_from_durable_receipts':True,
        'original_coordinator_failed':True,'exact_full_wall_seconds':None,'elapsed_scope':'Measured recorder-header to final span lower bound; early setup, later recovery and maintenance unmeasured.',
        'whole_campaign_usage_complete':False,'prior_unknown_preserved':True}
    save(root/'result.json',result)
    parent_path=Path(registration['parent_envelope']);parent=read(parent_path)
    save(root/'next-admission-envelope.json',dict(**close(parent,ledger,elapsed),parent_envelope=str(parent_path),parent_envelope_sha256=file_hash(parent_path),recovered_closure=True,exact_full_wall_seconds=None))
    print(dict(status='recovered',tokens=tokens,responses=count,measured_elapsed_lower_bound=elapsed,score=cell['score']['counts']))


if __name__=='__main__':main()
