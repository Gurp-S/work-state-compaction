"""Freeze coordinator-held chain material; no model dispatch or budget claim."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.chain_dataset import build_chain
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.task_specs import SPECS


def save(path,value):
    with path.open('x',encoding='utf-8') as out:
        json.dump(value,out,ensure_ascii=False,indent=2);out.write('\n')


def prepare(out,histories,seed,noise):
    out.mkdir(parents=True,exist_ok=False)
    private=out/'coordinator-private';private.mkdir()
    tasks={}
    for task,source in histories.items():
        before=source.read_bytes();initial=json.loads(before)
        schedule,oracle=build_chain(task,seed=seed,noise_per_round=noise,initial_history=initial['prefix'])
        if source.read_bytes()!=before:raise ValueError('chain_initial_history_changed')
        folder=private/task;folder.mkdir()
        save(folder/'schedule.json',schedule);save(folder/'oracles.json',oracle)
        starter=folder/'starter';starter.mkdir()
        for name in (SPECS[task]['entry'],'test_smoke.py'):
            shutil.copyfile(ROOT/'benchmarks/acceptance_matrix_v1/tasks'/SPECS[task]['folder']/'starter'/name,starter/name)
        tasks[task]=dict(input_path=str(source),input_sha256=sha256(before).hexdigest(),
            initial_history_sha256=seal(initial['prefix']),initial_event_count=len(initial['prefix']),
            schedule_sha256=seal(schedule),rounds=6,checkpoints=[2,4,6],history_dependency_qualified=False,
            artifacts={str(p.relative_to(out)):sha256(p.read_bytes()).hexdigest()
                       for p in folder.rglob('*') if p.is_file()})
    registration=dict(schema='wsc.acceptance.six_round_preparation/1',tasks=tasks,seed=seed,
        noise_per_round=noise,model_calls=0,paid_dispatch_authorized=False,
        model=None,execution_budget=None,compression_adapters_qualified=False,
        matrix_sha256=sha256((ROOT/'reviews/2026-10-28-acceptance-matrix.md').read_bytes()).hexdigest(),
        scope='Prepared data only. Future round schedule and all oracles remain coordinator-side. '
              'Only initial history, starter code and currently released events reach either arm.')
    save(out/'preparation.json',registration)
    return registration


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--t1-history',type=Path,required=True)
    parser.add_argument('--t3-history',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=20261030)
    parser.add_argument('--noise-per-round',type=int,default=2)
    args=parser.parse_args()
    value=prepare(args.out,{'T1':args.t1_history,'T3':args.t3_history},args.seed,args.noise_per_round)
    print(json.dumps(dict(tasks={k:dict(initial_events=v['initial_event_count'],rounds=v['rounds'])
                               for k,v in value['tasks'].items()},model_calls=0,dispatch=False)))
