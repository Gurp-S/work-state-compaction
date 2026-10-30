"""Owned runtime open/close qualification; provider exchange is forbidden."""
import argparse
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks')]
from native_chain_runtime import RuntimeOwner,ChainRuntimeFactory
from native_linux_python import DIRECTORY
from qualify_linux_python import checked_runtime
from acceptance_matrix_v1.phase_timing import PhaseTiming


def qualify(out):
    out.mkdir(parents=True,exist_ok=False)
    owner=None;factory=None;timing=PhaseTiming();calls=[];error=None;cleanup=None
    try:
        owner=RuntimeOwner(owned_distribution='docker-desktop')
        runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64')
        def forbidden(raw):calls.append(1);raise AssertionError('provider_exchange_forbidden')
        def verify(native,python):return dict(native=checked_runtime(native),python=checked_runtime(python))
        starter=ROOT/'benchmarks/acceptance_matrix_v1/tasks/t1_retry/starter'
        history=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1/coordinator-private/inputs.json')
        prefix=json.loads(history.read_bytes())['prefix']
        factory=ChainRuntimeFactory(owner,out/'arm',runtime=runtime,python=runtime.parent/DIRECTORY,
            model='gpt-6.1-sol',effort='max',max_calls=2,lifetime_seconds=360,exchange=forbidden,timing=timing,
            verify_runtime=verify,starter_files={name:starter/name for name in ('retry_client.py','test_smoke.py')})
        with timing.measure('lifecycle'):
            session=factory.open_with_history(prefix,lambda:dict(max_total_tokens=1000,max_responses=2,max_seconds=120))
            if session.opened['model']!='gpt-6.1-sol' or not (session.workspace_path()/'retry_client.py').is_file():
                raise ValueError('chain_factory_open_binding_changed')
            session.close()
    except Exception as exc:error=dict(type=type(exc).__name__,code=str(exc))
    finally:
        if owner:cleanup=owner.close()
    result=dict(qualified=error is None and cleanup and cleanup['closed'] and not calls,error=error,
        cleanup=cleanup,model_calls=len(calls),timing=timing.snapshot(),
        scope='Actual native process bootstrap/import/close only; no model request or chain task.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--owned-wsl-distribution',action='store_true',required=True)
    args=parser.parse_args();qualify(args.out)
