"""Single evidence-led startup diagnostic; no tool execution or model request."""
import argparse
import json
from pathlib import Path
import sys
import time
from hashlib import sha256

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.permissions import PROFILE,permission_flags
from native_blackbox_sessions import fresh
from native_evidence import save
from native_rpc import NativeRPC


def main(baseline,label,flag):
    plan=json.loads((baseline/'registration.json').read_text(encoding='utf-8'))
    destination=baseline/'coordinator-private'/label
    work=baseline/'A'
    blocked=plan['blocked']+[str(baseline/p) for p in plan['workspace_names'] if baseline/p!=work]
    flags=permission_flags(work,blocked)+plan.get('runtime_startup_flags',[])+([flag] if flag else [])
    reg=dict(workspace=str(work),executable=plan['executable'],executable_sha256=plan['executable_sha256'],**plan['model'])
    if destination.exists():raise ValueError('diagnostic_destination_exists')
    save(destination.parent/(label+'.registration.json'),dict(baseline=str(baseline),
        baseline_sha256=sha256((baseline/'registration.json').read_bytes()).hexdigest(),
        additional_flag=flag,startup_timeout_seconds=60,model_turns_started=0,
        scope='Only startup, not compression quality or normal native configuration.'))
    started=time.monotonic();session=None
    original=NativeRPC.__init__
    def instrumented(rpc,*args,**kwargs):
        original(rpc,*args,**kwargs)
        save(destination/'native-root.json',dict(pid=rpc.proc.pid,executable=plan['executable'],workspace=str(work)))
    NativeRPC.__init__=instrumented
    try:
        session=fresh(reg,destination,host_permissions=dict(profile=PROFILE,startup_flags=flags),startup_timeout=60)
        result=dict(started=True,thread_id=session.opened['thread']['id'],model_turns_started=0)
    except Exception as error:
        result=dict(started=False,error_type=type(error).__name__,error=str(error),model_turns_started=0)
    finally:
        NativeRPC.__init__=original
        if session is not None:session.close()
    result['seconds']=time.monotonic()-started
    save(destination/'diagnostic-result.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--label',required=True)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--skip-host-skill-discovery',action='store_true')
    mode.add_argument('--baseline-only',action='store_true')
    a=p.parse_args();main(a.baseline.resolve(),a.label,'features.skip_host_skill_discovery=true' if a.skip_host_skill_discovery else None)
