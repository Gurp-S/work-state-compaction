"""Seal T3 fixtures and admit existing native runtime/material with no model calls."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.workspace_runtime import provision_pair,environment_facts,qualify_pair
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.paired_cell import save


def file_hash(path):
    with Path(path).open('rb') as f:
        return sha256(f.read()).hexdigest()


def main(out,executable,*,disable_node_repl=False):
    history_root=Path('D:/agent-task-runs').resolve()
    if out.is_relative_to(history_root):
        raise ValueError('t3_public_workspace_must_be_outside_denied_history_root')
    out.mkdir(parents=True,exist_ok=False)
    private=out/'coordinator-private';private.mkdir()
    fixture=Path('D:/agent-task-runs/wsc-matrix-task-admission-20261028-v2/T3')
    pins=json.loads((ROOT/'reviews/acceptance-matrix-admission-20261028/t1-t3-delivery-pins.json').read_text(encoding='utf-8'))
    manifest_path=fixture/'fixture-manifest.json'
    if file_hash(manifest_path)!=pins['fixture_manifest_sha256'][str(manifest_path)]:raise ValueError('t3_fixture_manifest_changed')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        if file_hash(fixture/name)!=expected:raise ValueError('t3_fixture_file_changed:'+name)
    evaluator=ROOT/'benchmarks/acceptance_matrix_v1/acceptors.py'
    if file_hash(evaluator)!=pins['files']['wsc/benchmarks/acceptance_matrix_v1/acceptors.py']:raise ValueError('t3_evaluator_changed')
    inputs=json.loads((fixture/'history.public.json').read_text(encoding='utf-8'))
    if inputs['task']!='T3' or seal(inputs)!=manifest['public_sha256']:raise ValueError('t3_public_material_changed')
    for arm in ('A','last-state-only'):
        work=out/arm;work.mkdir()
        for name in ('migrate.py','test_smoke.py'):
            shutil.copy2(fixture/'public-starter'/name,work/name)
    runtime=provision_pair(Path('D:/agent-task-runs/wsc-matrix-python-admission-20261028-v4/public/.runtime'),out,arms=('A','last-state-only'))
    inputs['prefix'].append({'type':'message','role':'user','content':[{'type':'input_text','text':json.dumps(environment_facts(runtime),sort_keys=True)}]})
    save(private/'inputs.json',inputs)
    # Reuse the admitted T1 oracle/history boundary, then add T3's actual private
    # locations. Broad repository/history denials trigger expensive native ACL setup.
    previous=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1/registration.json')
    inherited=json.loads(previous.read_text(encoding='utf-8'))['blocked']
    blocked=[*inherited,str(private),str(fixture.parent)]
    blocked.extend(str(p/'coordinator-private') for p in out.parent.iterdir() if p!=out and (p/'coordinator-private').is_dir())
    blocked.extend(str(p/'coordinator-private') for p in history_root.glob('wsc-t3-runtime-admission-20261029-v*') if (p/'coordinator-private').is_dir())
    plan=dict(task_id='T3',executable=str(executable),executable_sha256=file_hash(executable),
        startup_timeout_seconds=60,
        runtime_startup_flags=['mcp_servers.node_repl.enabled=false'] if disable_node_repl else [],
        model=dict(model='gpt-6.1-sol',effort='max'),blocked=blocked,
        workspace_names=['A','last-state-only'],runtime_arms=['A','last-state-only'],runtime=runtime)
    probes=[fixture/'coordinator-private/oracle.json',evaluator,ROOT/'benchmarks/acceptance_matrix_v1/task_specs.py']
    save(out/'registration.json',dict(**plan,purpose='no_inference_T3_runtime_material_admission',
        fixture_manifest_sha256=file_hash(manifest_path),inputs_sha256=seal(inputs),
        inherited_boundary_registration=str(previous),inherited_boundary_sha256=file_hash(previous),
        private_probe_paths=[str(p) for p in probes],model_calls=0))
    try:
        result=qualify_pair(plan,out,material_inputs=inputs,private_probes=probes)
    except BaseException as error:
        save(out/'qualification-error.json',dict(type=type(error).__name__,error=str(error),model_calls=0))
        raise
    save(out/'results.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path,required=True)
    p.add_argument('--disable-node-repl',action='store_true',help='Diagnostic only; not a qualified performance optimization.')
    a=p.parse_args();main(a.output.resolve(),a.executable.resolve(),disable_node_repl=a.disable_node_repl)
