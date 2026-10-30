"""No-inference qualification of shared runtime provisioning and native admission."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'experiments')]
from acceptance_matrix_v1.workspace_runtime import provision_pair,qualify_pair,digest,environment_facts


def main(out,source,executable,history=None):
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    private=out/'coordinator-private';private.mkdir()
    arms=('A','last-state-only') if history else ('Bprime','C')
    for name in arms:(out/name).mkdir()
    binding=provision_pair(source,out,arms=arms)
    plan=dict(runtime=binding,executable=str(executable.resolve()),executable_sha256=digest(executable),
              model=dict(model='gpt-6.1-sol',effort='max'),blocked=[str(private)],
              environment_facts=environment_facts(binding),model_calls=0,runtime_arms=list(arms),workspace_names=list(arms))
    inputs=json.loads(history.read_text(encoding='utf-8')) if history else None
    if history:plan['public_history_sha256']=digest(history)
    (out/'registration.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    result=qualify_pair(plan,out,material_inputs=inputs)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--history',type=Path)
    args=parser.parse_args();main(args.out,args.source,args.executable,args.history)
