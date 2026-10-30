"""Clone prior native persistence; inspect actual requests to a local sink only."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'validation')]
from qualify_native_provider_bridge import BridgeRPC
from qualify_linux_python import checked_runtime,linux,save
from native_linux_python import command,DIRECTORY


def names(value):
    result=[]
    if type(value) is dict:
        if type(value.get('name')) is str:result.append(value['name'])
        for child in value.values():result.extend(names(child))
    elif type(value) is list:
        for child in value:result.extend(names(child))
    return result


def code_tool_definition(request):
    definitions=[]
    for item in request.get('input',[]):
        if item.get('type')!='additional_tools':continue
        for namespace in item.get('tools',[]):
            if namespace.get('type')!='namespace' or namespace.get('name')!='functions':continue
            definitions.extend(tool for tool in namespace.get('tools',[]) if tool.get('type')=='custom' and tool.get('name')=='exec')
    if not definitions:raise ValueError('request_code_tools_missing')
    return definitions[-1]


def context_declaration(definition):
    text=definition.get('description','');marker='### `WSCContext`\n'
    if text.count(marker)!=1:raise ValueError('context_declaration_ambiguous_or_missing')
    start=text.index(marker);ends=[n for n in (text.find('\n## ',start+len(marker)),
        text.find('\n### ',start+len(marker))) if n>=0]
    return text[start:min(ends) if ends else len(text)].rstrip()


def main(out,*,builtin=False,remote_v2=False,config_only=False):
    if builtin and remote_v2:raise ValueError('probe_provider_modes_conflict')
    state=subprocess.run(['wsl','--list','--verbose'],capture_output=True,timeout=10)
    if state.returncode or 'Running' in state.stdout.decode('utf-16-le') or 'Stopped' not in state.stdout.decode('utf-16-le'):
        raise ValueError('wsl_not_owned_stopped')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    origin=Path('D:/agent-task-runs/wsc-mapped-checkpoint-20261030-v1');actor=out/'actor-root';actor.mkdir();(actor/'actor').mkdir()
    home=origin/'actor-root/home';files={}
    # Previous process is stopped. Copy persistent native records, excluding
    # ephemeral argument helpers/links. Never mutate the original evidence.
    for p in home.rglob('*'):
        relative=p.relative_to(home)
        if '.tmp' in relative.parts:continue
        if not p.is_file():continue
        if p.is_symlink():raise ValueError('native_persistence_link_unregistered')
        raw=p.read_bytes();files[str(relative)]=sha256(raw).hexdigest()
        target=actor/'home'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    actor_source=ROOT/'validation'/('native_local_websocket_actor.py' if builtin else 'native_local_protocol_actor.py')
    shutil.copyfile(actor_source,actor/'protocol-actor.py')
    vendor={}
    if builtin:
        import websockets
        source=Path(websockets.__file__).parent
        for p in source.rglob('*.py'):
            raw=p.read_bytes();relative=p.relative_to(source);target=actor/'fixture-vendor/websockets'/relative
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            vendor[str(relative)]=sha256(raw).hexdigest()
        save(private/'fixture-websocket-vendor.json',dict(version=websockets.__version__,source=str(source),
            files=vendor,scope='Existing installed pure Python files for local fixture only; no global installation'))
    (actor/'probe-phase.txt').write_text('resumed_tools')
    runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64');python=runtime.parent/DIRECTORY
    owner=json.loads((origin/'coordinator-private/session-1/thread-start.json').read_bytes())['thread']['id']
    args=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','70']+command(linux(runtime),linux(actor),linux(python))+[
        '/opt/python/bin/python3.11','-I','-B','/work/protocol-actor.py']+(['--remote-v2'] if remote_v2 else [])+[
        '/opt/codex/bin/codex','app-server','--stdio',
        '-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    save(private/'registration.json',dict(real_model_calls=0,remote_forwarding=False,origin=str(origin),
        origin_home_sha256=files,source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),actor_source]},
        runtime=dict(native=checked_runtime(runtime),python=checked_runtime(python)),
        requests_cap=4,websocket_frame_cap=8 if builtin else None,native_thread_id=owner,provider_mode='builtin_openai_local_placeholder_key' if builtin else 'named_custom_remote_v2' if remote_v2 else 'named_custom_provider',
        expected_compaction_response='Explicit local 501; not simulated Codex compression'))
    rpc=None;events=[];callbacks=[]
    def wait(phase,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:event=rpc.event(timeout=.5)
            except queue.Empty:continue
            events.append(dict(phase=phase,event=event))
            if event.get('method')=='item/tool/call':
                params=event['params']
                if phase!='resumed_tools' or params.get('tool')!='WSCContext' or params.get('arguments')!={'operation':'describe','reference':'source:s45'}:
                    raise ValueError('local_probe_callback_mismatch')
                callbacks.append(event)
                rpc.send(dict(id=event['id'],result=dict(contentItems=[dict(type='inputText',text='{"local_fixture_registered":true}')],success=True)))
            if event.get('method') in ('error','turn/completed'):return event
        return None
    try:
        rpc=BridgeRPC(args,private/'stderr.txt')
        rpc.call('initialize',dict(clientInfo=dict(name='wsc_local_route_probe',version='1'),capabilities=dict(experimentalApi=True)),timeout=15)
        rpc.send(dict(method='initialized'))
        resumed=rpc.call('thread/resume',dict(threadId=owner,cwd='/work/actor',model='gpt-6.1-sol',
            modelProvider='openai' if builtin else 'wsc_fixture',approvalPolicy='never',sandbox='read-only'),timeout=20)
        save(private/'resumed.json',resumed)
        configuration=rpc.call('config/read',dict(includeLayers=False),timeout=10)
        save(private/'config-read.json',configuration)
        if config_only:
            config=configuration.get('config',configuration);provider='openai' if builtin else 'wsc_fixture'
            entry=config.get('model_providers',{}).get(provider,{})
            save(out/'results.json',dict(real_model_calls=0,config_only=True,provider=provider,
                provider_capabilities=entry.get('capabilities'),supports_websockets=entry.get('supports_websockets'),
                original_auth_not_loaded=True,local_placeholder_key_only=builtin,paid_dispatch_admitted=False))
            print(json.dumps(json.loads((out/'results.json').read_bytes())))
            return
        rpc.call('turn/start',dict(threadId=owner,model='gpt-6.1-sol',effort='max',
            input=[dict(type='text',text='Local request schema observation fixture.')]),timeout=10)
        terminal=wait('resumed_tools',15)
        if not terminal or terminal['method']!='turn/completed' or terminal['params']['turn']['status']!='completed':
            raise ValueError('resumed_schema_probe_not_complete')
        captured=sorted((actor/'protocol-fixture').glob('*-request.json'))
        candidate=[json.loads(p.read_bytes()) for p in captured]
        first=next((d for d in candidate if any(i.get('type')=='additional_tools' for i in d.get('input',[]))),None)
        if first is None:raise ValueError('resumed_tools_full_request_unobserved')
        fresh=Path('D:/agent-task-runs/wsc-live-context-recovery-20261030-v2/coordinator-private/requests/001-request.json')
        actual=code_tool_definition(first);expected=code_tool_definition(json.loads(fresh.read_bytes()))
        if context_declaration(actual)!=context_declaration(expected) or len(callbacks)!=1:raise ValueError('resumed_context_tool_missing')
        tool_names=names(actual)
        save(private/'tool-definition-proof.json',dict(reference=str(fresh),reference_sha256=sha256(fresh.read_bytes()).hexdigest(),
            full_code_tool_definition_equal=actual==expected,context_tool_declaration_equal=True,
            context_declaration_sha256=sha256(context_declaration(actual).encode()).hexdigest(),
            definition_sha256=sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest(),
            actual_native_callbacks=callbacks,callback_response='Local fixture only; not a source recovery proof'))
        (actor/'probe-phase.txt').write_text('compaction_route')
        rpc.call('thread/compact/start',dict(threadId=owner),timeout=10)
        wait('compaction_route',20)
        metadata=[json.loads(p.read_bytes()) for p in sorted((actor/'protocol-fixture').glob('*-metadata.json'))]
        compact=[v for v in metadata if v['phase']=='compaction_route' and not v.get('prewarm',False)]
        if not compact:raise ValueError('native_compaction_route_unobserved')
        for relative,h in files.items():
            if sha256((home/relative).read_bytes()).hexdigest()!=h:raise ValueError('original_native_evidence_mutated')
        save(private/'events.json',events);save(private/'captured-routes.json',metadata)
        for p in (actor/'protocol-fixture').iterdir():shutil.copyfile(p,private/p.name)
        save(out/'results.json',dict(real_model_calls=0,native_resumed_request_tool_schema_verified=True,
            provider_mode='builtin_openai_local_placeholder_key' if builtin else 'named_custom_remote_v2' if remote_v2 else 'named_custom_provider',
            dynamic_tools_resupplied=False,tool_names=tool_names,resumed_native_dynamic_callback_verified=True,
            compaction_routes=[v['path'] for v in compact],
            native_compaction_completed=False,local_compaction_response_status=501,
            original_evidence_unchanged=True,paid_dispatch_admitted=False,
            scope='Actual native request construction to scripted local HTTP sink; no model/compression outcome'))
        print(json.dumps(json.loads((out/'results.json').read_bytes())))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),real_model_calls=0));raise
    finally:
        if not (private/'events.json').exists():save(private/'events.json',events)
        if rpc and rpc.proc.stdin and not rpc.proc.stdin.closed:rpc.proc.stdin.close()
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))
        if rpc:rpc.proc.wait(timeout=5);rpc.proc.stdout.close();rpc.stderr.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--owned-wsl-distribution',action='store_true',required=True)
    p.add_argument('--builtin-openai',action='store_true');p.add_argument('--remote-v2',action='store_true')
    p.add_argument('--config-only',action='store_true');a=p.parse_args()
    main(a.out.resolve(),builtin=a.builtin_openai,remote_v2=a.remote_v2,config_only=a.config_only)
