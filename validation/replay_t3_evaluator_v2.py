"""Uniform post-hoc audit of retained artifacts; never overwrites registered scores."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.acceptors import load_candidate
from acceptance_matrix_v1.acceptor_t3_v2 import accept_t3_v2
from acceptance_matrix_v1.final_assertions import score_final
from acceptance_matrix_v1.final_origin import score_bound_final


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    controls=Path('D:/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7')
    fixture=Path('D:/agent-task-runs/wsc-matrix-task-admission-20261028-v2/T3')
    oracle=read(fixture/'coordinator-private/oracle.json')
    bindings={};results={}
    for name,path in {'A':controls/'A/migrate.py','last-state-only':controls/'last-state-only/migrate.py',
                      'reference':fixture/'coordinator-private/reference-smoke/migrate.py',
                      'starter':fixture/'public-starter/migrate.py'}.items():
        bindings[str(path)]=digest(path)
        result=accept_t3_v2(load_candidate(path))
        if name in ('A','last-state-only'):
            original_path=controls/'coordinator-private'/name/'result.json'
            bindings[str(original_path)]=digest(original_path)
            original=read(original_path)
            if result['legacy_result']['checks']!=original['checks']:raise ValueError('legacy_artifact_result_changed:'+name)
            area=controls/'coordinator-private'/name/'continuation'
            for p in (area/'phase-outcome.json',area/'rollout.jsonl'):bindings[str(p)]=digest(p)
            result['final_audit']=score_bound_final(read(area/'phase-outcome.json'),oracle,area/'rollout.jsonl')
        results[name]=result
    t1=[]
    for label,base in [('r1',Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')),
                       ('r2',Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1/r2')),
                       ('r3',Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1/r3'))]:
        parent=base if label=='r1' else base.parent
        known_oracle=read(read(parent/'registration.json')['oracle_path'])
        for arm in ('Bprime','C'):
            area=base/'coordinator-private'/arm/'continuation'
            phase=read(area/'phase-outcome.json');old=score_final(phase,known_oracle)
            new=score_bound_final(phase,known_oracle,area/'rollout.jsonl')
            keys=('required_assertions','submitted_assertions','citation_byte_matches','exact_answer_correct','output_parse_error','final_answer_count')
            if any(old[k]!=new[k] for k in keys):raise ValueError('t1_compatibility_changed:'+label+':'+arm)
            t1.append(dict(case=label+':'+arm,matched_metrics={k:new[k] for k in keys}))
            for p in (area/'phase-outcome.json',area/'rollout.jsonl'):bindings[str(p)]=digest(p)
    if any(digest(p)!=value for p,value in bindings.items()):raise ValueError('retained_evidence_changed')
    sources={str(ROOT/p):digest(ROOT/p) for p in ('benchmarks/acceptance_matrix_v1/acceptor_t3_v2.py',
        'benchmarks/acceptance_matrix_v1/final_origin.py','validation/replay_t3_evaluator_v2.py')}
    summary=dict(scope='Post-hoc audit only; original registration/grade/budget preserved',model_calls=0,
        results=results,t1_compatibility=t1,retained_file_hashes=bindings,evaluator_hashes=sources,
        history_dependency_qualified=False,new_BC_experiment=False,interrupted_usage_still_unknown=True)
    with (out/'results.json').open('x',encoding='utf-8') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(model_calls=0,code_pass={k:sum(r['passed'] is True for r in v['checks']) for k,v in results.items()},
        compatibility_cases=len(t1),history_dependency_qualified=False)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();main(a.out.resolve())
