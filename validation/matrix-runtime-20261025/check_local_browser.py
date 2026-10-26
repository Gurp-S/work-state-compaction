"""Same browser bytes inside a writable workspace, same native policy, no model."""
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,manifest
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings

AREA=Path('D:/agent-task-runs/wsc-browser-capability-20261025-v1')
WORK=AREA/'work'
CACHE=WORK/'browser-cache'
CACHE.mkdir(exist_ok=False)
BASE=Path('C:/Users/48522/AppData/Local/ms-playwright')
pins={}
for name in ('chromium-1234','chromium_headless_shell-1234'):
    source=BASE/name
    before=manifest(source)
    shutil.copytree(source,CACHE/name)
    assert manifest(CACHE/name)==before
    pins.update({name+'/'+key:value for key,value in before.items()})
save(AREA/'local-browser-binding.json',dict(cache=str(CACHE),source=str(BASE),files=pins,
    copy_kind='physical_private',source_unchanged=True))
reg=read(Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/registration.json'))
native_settings=settings(dict(effort='max',host_feature_overrides=reg['conditions']['host_feature_overrides']))
import json
native_settings.append('shell_environment_policy.set.PLAYWRIGHT_BROWSERS_PATH='+json.dumps(str(CACHE)))
server=OwnedNativeRPC(reg['conditions']['executable']['path'],cwd=WORK,
    stderr_path=AREA/'local-browser-stderr.txt',settings=native_settings)
observations={}
try:
    server.call('initialize',dict(clientInfo=dict(name='wsc_local_browser_probe',version='1'),capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    for mode in ('default','full'):
        output=WORK/('native_local-'+mode)
        result=server.call('command/exec',dict(command=[reg['node_executable'],str(WORK/'browser_capability.mjs'),
            'D:/agent-task-runs/wsc-a3-qualification-20261025-v1/arms/B/workspace/gui',str(output),mode],
            cwd=str(WORK),sandboxPolicy=dict(type='workspaceWrite',writableRoots=[str(WORK)],networkAccess=False),timeoutMs=35000),timeout=45)
        save(AREA/('native-local-'+mode+'-execution.json'),result)
        observed=read(output/'result.json') if (output/'result.json').exists() else dict(passed=False,error='command_did_not_write_result')
        observations[mode]=observed
        print(mode,observed['passed'],str(observed.get('error',''))[:200],flush=True)
finally:
    cleanup=server.close()
    save(AREA/'local-browser-cleanup.json',cleanup)
save(AREA/'local-browser-result.json',dict(observations=observations,cleanup=cleanup,model_calls=0,
    settings=native_settings,policy=dict(type='workspaceWrite',networkAccess=False),
    scope='Command/exec native sandbox; both browser launch, loopback navigation and screenshot'))
