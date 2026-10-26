"""Bounded live tool-route qualification after zero-inference capability proof."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash
from native_application_capability import materialize,admit
from native_application_session import NativeApplicationSession

AREA=Path('D:/agent-task-runs/wsc-browser-model-route-20261025-v1')
AREA.mkdir(exist_ok=False)
prior=read(Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/registration.json'))
assert read(Path('D:/agent-task-runs/wsc-browser-capability-20261025-v1/local-browser-result.json'))['observations']['default']['passed']
work=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/arms/B/workspace')
binding=Path('D:/agent-task-runs/wsc-browser-capability-20261025-v1/local-browser-binding.json')
runtime=materialize(work,dict(binding=str(binding),binding_sha256=file_hash(binding),
    probe=str(HERE/'browser_capability.mjs'),probe_sha256=file_hash(HERE/'browser_capability.mjs')))
old=read(Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1/prepared/payload-B.json'))['registration']
reg={**old,**runtime,'node_executable':prior['node_executable']}
session=NativeApplicationSession(reg,AREA/'native')
reg['initial_manifest']=session.source_manifest()
journal=[]
try:
    session.open()
    admit(session,AREA/'zero-call-preflight')
    witness=AREA/'cold-source.json'
    save(witness,dict(kind='cold_source_probe',value='source_identity_and_bytes'))
    command=[prior['node_executable'],'-e',"const fs=require('node:fs'); const crypto=require('node:crypto'); console.log(crypto.createHash('sha256').update(fs.readFileSync(process.argv[1])).digest('hex'));",str(witness)]
    cold=session.server.call('command/exec',dict(command=command,cwd=str(work),sandboxPolicy=dict(type='readOnly',networkAccess=False),timeoutMs=10000),timeout=20)
    save(AREA/'read-only-cold-access.json',cold)
    assert cold['exitCode']==0 and cold['stdout'].strip()==file_hash(witness),'native_readonly_cold_source_inaccessible'
    output=Path(reg['browser_cache']).parent/'model-route-result'
    argv=[reg['node_executable'],reg['browser_probe'],str(work/'gui'),str(output),'default']
    request=('实际执行这一条本机浏览器能力验证命令，并返回它生成的 result.json 内容。这是独立工具通道验证。\n'
             + '& '+' '.join("'"+value.replace("'","''")+"'" for value in argv))
    phase=session.execute_stage(request,AREA/'phase',dict(max_responses=4,max_seconds=90,max_total_tokens=160000),journal.append)
finally:
    cleanup=session.close()
observed=read(output/'result.json') if (output/'result.json').exists() else dict(passed=False,error='model_tool_route_no_result')
save(AREA/'result.json',dict(phase=phase,journal_entries=len(journal),cleanup=cleanup,
    browser_result=observed,workspace_source_unchanged=session.source_manifest()==reg['initial_manifest'],
    current_work_scope='Interrupted A3 workspace used only for browser transport; not task continuation or B/C result',
    before='Native browser cache outside workspace unavailable',after='Private exact browser bytes and configured native shell environment'))
print(json.dumps(dict(passed=observed['passed'],phase_completed=phase['completed'],usage_complete=phase.get('usage_complete'),
    responses=phase.get('receipts',{}).get('response_count'),tokens=phase.get('receipts',{}).get('all_usage',{}).get('total_tokens'),
    failure=phase.get('failure'),cleanup=cleanup),ensure_ascii=False))
