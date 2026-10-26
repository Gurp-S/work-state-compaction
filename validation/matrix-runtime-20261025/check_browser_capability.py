"""Compare parent and native command execution; zero thread/turn creation."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
from native_owned_process import OwnedNativeRPC,ProcessOwner
from native_host_controls import settings

AREA=Path('D:/agent-task-runs/wsc-browser-capability-20261025-v1')
WORK=AREA/'work'
WORK.mkdir(exist_ok=False)
SCRIPT=WORK/'browser_capability.mjs'
shutil.copyfile(HERE/'browser_capability.mjs',SCRIPT)
reg=read(Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/registration.json'))
gui=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/arms/B/workspace/gui')
exe=reg['conditions']['executable']['path']
assert file_hash(exe)==reg['conditions']['executable']['sha256']
server=OwnedNativeRPC(exe,cwd=WORK,stderr_path=AREA/'stderr.txt',settings=settings(dict(
    effort='max',host_feature_overrides=reg['conditions']['host_feature_overrides'])))
observations={}
try:
    save(AREA/'initialized.json',server.call('initialize',dict(clientInfo=dict(name='wsc_capability_probe',version='1'),
        capabilities=dict(experimentalApi=True))))
    server.send(dict(method='initialized'))
    config=server.call('config/read',dict(includeLayers=False))
    save(AREA/'execution-config.json',{key:config.get('config',{}).get(key) for key in ('windows','sandbox_mode','approval_policy')})
    for mode in ('default','full'):
        for environment in ('parent','native_workspace'):
            output=WORK/(environment+'-'+mode)
            command=[reg['node_executable'],str(SCRIPT),str(gui),str(output),mode]
            if environment=='parent':
                owner=ProcessOwner()
                proc=None
                try:
                    proc=subprocess.Popen(command,cwd=WORK,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    owner.attach(proc)
                    stdout,stderr=proc.communicate(timeout=35)
                    execution=dict(exitCode=proc.returncode,stdout=stdout,stderr=stderr)
                finally:
                    save(AREA/(environment+'-'+mode+'-cleanup.json'),owner.close())
            else:
                execution=server.call('command/exec',dict(command=command,cwd=str(WORK),
                    sandboxPolicy=dict(type='workspaceWrite',writableRoots=[str(WORK)],networkAccess=False),timeoutMs=35000),timeout=45)
            save(AREA/(environment+'-'+mode+'-execution.json'),execution)
            observed=read(output/'result.json') if (output/'result.json').exists() else dict(passed=False,error='command_did_not_write_result')
            observations[environment+'-'+mode]=observed
            print(environment,mode,observed['passed'],str(observed.get('error',''))[:120],flush=True)
finally:
    cleanup=server.close()
    save(AREA/'cleanup.json',cleanup)
save(AREA/'result.json',dict(observations=observations,cleanup=cleanup,model_calls=0,threads_created=0,
    scope='Native command/exec policy, not yet proof of every model-visible execution route',
    script_sha256=file_hash(SCRIPT)))
