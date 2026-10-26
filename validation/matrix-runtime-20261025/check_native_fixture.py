"""Qualify the real A3 fixture host on the repaired native execution route."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings

AREA=Path('D:/agent-task-runs/wsc-native-a3-fixture-capability-20261025-v1')
AREA.mkdir(exist_ok=False)
reg=read(Path('D:/agent-task-runs/wsc-browser-model-route-20261025-v1/native/registration.json'))
work=Path(reg['workspace'])
output=Path(reg['browser_cache']).parent/'native-fixture-check'
harness=Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1/frozen-workspace/task-contract/a3-ui-long-v1/harness/run-acceptance.mjs')
server=OwnedNativeRPC(reg['executable'],cwd=work,stderr_path=AREA/'stderr.txt',settings=settings(reg))
try:
    server.call('initialize',dict(clientInfo=dict(name='wsc_fixture_probe',version='1'),capabilities=dict(experimentalApi=True)))
    server.send(dict(method='initialized'))
    execution=server.call('command/exec',dict(command=[reg['node_executable'],str(harness),str(work/'gui'),str(output),'S1','none','C01'],
        cwd=str(work),sandboxPolicy=dict(type='workspaceWrite',writableRoots=[str(work)],networkAccess=False),timeoutMs=120000),timeout=130)
    save(AREA/'execution.json',execution)
finally:
    cleanup=server.close()
    save(AREA/'cleanup.json',cleanup)
observed=read(output/'result.json') if (output/'result.json').exists() else dict(status='incomplete')
save(AREA/'result.json',dict(native_fixture_completed=execution.get('exitCode')==0 and observed.get('status')=='completed_checks',
    observed=observed,output=str(output),cleanup=cleanup,model_calls=0,
    scope='Real native fixture capability against interrupted partial B source; not full task or B/C qualification'))
print(dict(native_fixture_completed=observed.get('status')=='completed_checks',auto_passed=observed.get('automated_passed'),cleanup=cleanup))
