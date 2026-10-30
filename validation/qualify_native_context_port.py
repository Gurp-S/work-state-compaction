"""Real native registration/mount proof plus an explicitly scripted callback.

No turn/start, model, native compaction or production installation is issued.
The docker-desktop WSL distribution must initially be stopped and caller-owned.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation')]
from wsc import WSC,Store
from wsc.contracts import encode
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore,ResultPolicy,ToolText
from native_linux_envelope import command as envelope
from native_context_recovery import open_context_receiver
from qualify_linux_native_protocol import ProbeRPC
from native_evidence import import_evidence,state


def save(p,v):
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)


def linux(path):return '/mnt/host/'+path.drive[0].lower()+'/'+path.as_posix().split(':/',1)[1]


def main(out):
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    actor=out/'actor-root';(actor/'actor').mkdir(parents=True);(actor/'home/.codex').mkdir(parents=True)
    runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64')
    manifest=json.loads((runtime/'runtime-manifest.json').read_text())
    for name,value in manifest['files'].items():
        h=sha256()
        with (runtime/name).open('rb') as f:
            for b in iter(lambda:f.read(1048576),b''):h.update(b)
        if h.hexdigest()!=value['sha256']:raise ValueError('native_context_runtime_changed')
    files=[*sorted((ROOT/'src/wsc').rglob('*.py')),
           ROOT/'experiments/native_context_recovery.py',ROOT/'experiments/native_context_workspace.py',Path(__file__)]
    command=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','90']+envelope(linux(runtime),linux(actor))+[
             '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    save(private/'registration.json',dict(command=command,source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in files},
        model='gpt-6.1-sol',effort='max',model_calls=0,callback_origin='Scripted host-contract fixture, not an LLM-emitted request',
        presentation_origin='Offline grant after actual native history import; not an observed model request'))
    core=WSC(Store(private/'core.db',session_id='context-probe',workspace=str(actor/'actor')),access=lambda *_:True)
    ctx=ContextRuntime(core,ResultStore(private/'result-store',session='context-probe'),policy=ResultPolicy(enabled=True))
    adapter=CodexCheckpointAdapter();ctx.observe(adapter.import_items([dict(type='message',role='user',content=[dict(type='input_text',text='Fixed context port fixture')])],thread_id='host-fixture'))
    rpc=None;session=None
    class Session:
        def __init__(self,server,opened):
            self.server=server;self.opened=opened;self.registration=dict(workspace='/work/actor');self.closed=False
        def close(self):self.closed=True
    def factory(**options):
        nonlocal rpc,session
        save(private/'tool-registration.json',options)
        rpc=ProbeRPC(command,private/'stderr.txt')
        save(private/'initialized.json',rpc.call('initialize',dict(clientInfo=dict(name='wsc_context_port_probe',version='1'),capabilities=dict(experimentalApi=True)),timeout=15))
        rpc.send(dict(method='initialized'))
        opened=rpc.call('thread/start',dict(cwd='/work/actor',model='gpt-6.1-sol',allowProviderModelFallback=False,
              approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=['/work/actor'],ephemeral=False,
              dynamicTools=options['dynamic_tools']),timeout=20)
        if opened['model']!='gpt-6.1-sol' or opened['reasoningEffort']!='max':raise ValueError('native_context_model_changed')
        save(private/'opened.json',opened);session=Session(rpc,opened);return session
    try:
        port=open_context_receiver(factory,ctx,ctx.capture(),actor_root=actor)
        script='i=0; while [ "$i" -lt 2500 ]; do printf "original producer row %s\\r\\n" "$i"; i=$((i+1)); done'
        response=rpc.call('command/exec',dict(command=['/bin/sh','-c',script],cwd='/work/actor',timeoutMs=10000),timeout=15)
        save(private/'producer-command.json',response)
        if response['exitCode']!=0:raise ValueError('native_context_producer_failed')
        wire=[dict(type='function_call',call_id='host-producer',name='host_command_fixture',arguments='{}'),
              dict(type='function_call_output',call_id='host-producer',output=response['stdout'])]
        call,result=adapter.import_items(wire,thread_id='host-fixture',start_ordinal=1)
        ctx.observe([call]);view=ctx.record_tool_result(result,ToolText(response['stdout'],kind='terminal_log',exit_code=0,facts={'stderr':response['stderr']}))
        if not view['external']:raise ValueError('native_context_view_not_external')
        save(private/'visible-view.json',view)
        projected=[wire[0],{**wire[1],'output':encode(view)}]
        rpc.call('thread/inject_items',dict(threadId=port.owner,items=projected),timeout=10)
        history=Path(session.opened['thread']['path']).relative_to('/work')
        raw=(actor/history).read_bytes();rows=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
        if any(r['type']=='token_usage_record' for r in rows):raise ValueError('native_context_unexpected_inference')
        proof=import_evidence(state(rows),projected)
        save(private/'import-proof.json',proof)
        if not proof['matched']:raise ValueError('native_context_history_projection_unobserved')
        (private/'rollout.jsonl').write_bytes(raw)
        # Explicit offline fixture receipt; never labeled actual LLM delivery.
        ctx.presented('offline-import-fixture',[result.id],receiver='offline-not-model-request')
        port.advance(ctx.capture())
        callback=dict(id='fixture-rpc',method='item/tool/call',params=dict(threadId=port.owner,turnId='fixture-turn',
             callId='fixture-query',tool='WSCContext',arguments=dict(operation='read',reference='result:'+view['result_id'],units='utf8_bytes',limit=256)))
        reply=port.handler.handle(callback,thread_id=port.owner,turn_id='fixture-turn')
        value=json.loads(reply['result']['contentItems'][0]['text'])
        if not reply['result']['success'] or not value['text'].startswith('original producer row 0\r\n'):raise ValueError('native_context_recovery_fixture_failed')
        save(private/'scripted-callback.json',dict(from_model=False,event=callback,reply=reply))
        probes=[linux(private/'core.db'),linux(private/'result-store/results.sqlite3'),'/proc/1/root'+linux(private/'core.db')]
        denied=rpc.call('command/exec',dict(command=['/bin/sh','-c','for p in "$@"; do if cat "$p" >/dev/null 2>&1; then exit 1; fi; done; printf private-unreadable','probe',*probes],cwd='/work/actor',timeoutMs=5000),timeout=10)
        save(private/'private-query-storage-probe.json',dict(paths=probes,response=denied))
        if denied.get('exitCode')!=0 or denied.get('stdout')!='private-unreadable':raise ValueError('native_context_private_storage_readable')
        save(out/'results.json',dict(model_calls=0,native_schema_registered=True,actual_workspace_mapping_verified=True,
            actual_native_producer=True,original_bytes=len(response['stdout'].encode()),model_view_bytes=len(encode(view).encode()),
            native_history_projection_verified=True,scripted_host_callback_exact=True,query_storage_private=True,
            actual_model_callback_verified=False,actual_model_delivery_verified=False,native_checkpoint_install_verified=False,
            paid_dispatch_admitted=False,scope='No-model native/host integration only'))
        print(json.dumps(json.loads((out/'results.json').read_text())))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),model_calls=0));raise
    finally:
        if rpc:
            save(private/'methods-issued.json',dict(methods=rpc.sent,model_requests_issued=0))
            if rpc.proc.stdin:rpc.proc.stdin.close()
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))
        if rpc:rpc.proc.wait(timeout=5);rpc.proc.stdout.close();rpc.stderr.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--owned-wsl-distribution',required=True,action='store_true')
    main(parser.parse_args().out.resolve())
