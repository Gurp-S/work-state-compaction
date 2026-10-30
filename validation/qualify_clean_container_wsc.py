"""No-pull, no-model WSC smoke inside an owned container with no host answers."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]

SMOKE = r'''
import json,os,socket,sqlite3,sys
from pathlib import Path
from hashlib import sha256
sys.path.insert(0,'/opt/wsc-src')
from wsc import WSC,Store,Selection
from wsc.adapters.codex import CodexCheckpointAdapter
work=Path('/work')
def message(role,text):
    return dict(type='message',role=role,content=[dict(type='input_text' if role=='user' else 'output_text',text=text)])
items=[message('user','fixture-control'),message('assistant','fixture-observation')]
core=WSC(Store(work/'state.db',session_id='container-smoke',workspace=str(work)),access=lambda *_:True)
adapter=CodexCheckpointAdapter()
ids=core.ingest(adapter.import_items(items,thread_id='container-fixture'))
snap=core.capture()
view=core.prepare(snap,Selection(),producer='deterministic-fixture')
op=core.stage(view,directory=work/'export',adapter=adapter)
package=core.package(op)
assert package['items'][0]==items[0]
raw=Path(package['evidence'][ids[1]]['file_path']).read_bytes()
assert json.loads(raw)==items[1]
reopened=WSC(Store(work/'state.db',session_id='container-smoke',workspace=str(work)),access=lambda *_:True)
assert reopened.capture().source_digest==snap.source_digest
assert reopened.package(op)['package_digest']==package['package_digest']
assert reopened.status()['cursor']==0
# Export is not a fake native installation receipt.
blocked_paths=['/var/run/docker.sock','/host_mnt','/run/desktop/mnt/host','/mnt/c/Users/48522/.codex/sessions','/mnt/d/agent-task-runs','/mnt/d/wsc-public-workspaces']
assert not any(Path(p).exists() for p in blocked_paths)
assert os.geteuid()!=0
read_only=False
try:Path('/opt/wsc-src/.write-probe').write_text('probe')
except (PermissionError,OSError):read_only=True
assert read_only
no_new_privs=next(line.split(':',1)[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('NoNewPrivs:'))
assert no_new_privs=='1'
interfaces=sorted(p.name for p in Path('/sys/class/net').iterdir())
assert interfaces==['lo']
print(json.dumps(dict(wsc_capture_prepare_stage=True,cold_original_roundtrip=True,reopen_state_verified=True,
 export_not_install=True,source_mount_readonly=read_only,host_paths_absent=blocked_paths,
 euid=os.geteuid(),network_interfaces=interfaces,no_new_privileges=True,python=sys.version.split()[0],
 sqlite=sqlite3.sqlite_version,source_count=len(ids),cold_sha256=sha256(raw).hexdigest(),model_calls=0)))
'''


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    source=ROOT/'src'
    pins={p.relative_to(source).as_posix():sha256(p.read_bytes()).hexdigest()
          for p in sorted(source.rglob('*.py'))}
    image=json.loads(subprocess.run(['docker','image','inspect','python:3.11-slim'],capture_output=True,
                    text=True,encoding='utf-8',check=True,timeout=10).stdout)[0]
    if image['Os']!='linux' or image['Architecture']!='amd64' or image['Config'].get('Volumes'):
        raise ValueError('container_base_not_admitted')
    name='wsc-clean-admission-'+uuid4().hex[:12]
    args=['docker','create','--pull','never','--name',name,'--network','none','--read-only',
          '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64',
          '--memory','256m','--cpus','1','--user','65534:65534',
          '--tmpfs','/work:rw,nosuid,noexec,size=16m,mode=1777',
          '--mount',f'type=bind,source={source},target=/opt/wsc-src,readonly',
          '--env','PYTHONDONTWRITEBYTECODE=1','--env','HOME=/work',
          '--workdir','/work','--entrypoint','python','-i',image['Id'],'-B','-']
    save(out/'registration.json',dict(image_id=image['Id'],source_sha256=pins,
         create_command=args,smoke_sha256=sha256(SMOKE.encode()).hexdigest(),model_calls=0,
         scope='Container filesystem and WSC core only; native CLI, live provider and model recovery unqualified'))
    (out/'smoke.py').write_text(SMOKE,encoding='utf-8')
    cid=None
    try:
        cid=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',check=True,timeout=15).stdout.strip()
        inspected=json.loads(subprocess.run(['docker','inspect',cid],capture_output=True,text=True,
                            encoding='utf-8',check=True,timeout=10).stdout)[0]
        mounts=inspected['Mounts']
        if len(mounts)!=1 or mounts[0]['Destination']!='/opt/wsc-src' or mounts[0]['RW']:
            raise ValueError('container_unregistered_mount')
        save(out/'container-boundary.json',dict(image=inspected['Image'],mounts=mounts,
             network_mode=inspected['HostConfig']['NetworkMode'],readonly_rootfs=inspected['HostConfig']['ReadonlyRootfs'],
             tmpfs=inspected['HostConfig']['Tmpfs']))
        response=subprocess.run(['docker','start','--attach','--interactive',cid],input=SMOKE,
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
        save(out/'execution.json',dict(exit_code=response.returncode,stdout=response.stdout,stderr=response.stderr))
        if response.returncode:raise ValueError('container_wsc_smoke_failed')
        observed=json.loads(response.stdout)
        after={p.relative_to(source).as_posix():sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*.py'))}
        if after!=pins:raise ValueError('container_source_changed_during_probe')
        save(out/'results.json',dict(qualified_for='offline_container_WSC_core_only',observed=observed,
             native_codex_qualified=False,BC_experiment=False,paid_dispatch_admitted=False,source_files_verified=len(pins)))
        print(json.dumps(dict(container_smoke_passed=True,source_files=len(pins),model_calls=0,native_codex_qualified=False)))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),model_calls=0))
        raise
    finally:
        if cid:
            removed=subprocess.run(['docker','rm','--force',cid],capture_output=True,text=True,encoding='utf-8',timeout=10)
            save(out/'cleanup.json',dict(container_id=cid,exit_code=removed.returncode,stdout=removed.stdout,stderr=removed.stderr))
            if removed.returncode:raise RuntimeError('container_cleanup_failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args().out.resolve())
