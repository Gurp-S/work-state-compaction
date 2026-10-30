"""Closed-mount native transport with a scripted provider, never an LLM test."""
import argparse
from base64 import b64encode
from hashlib import sha256
import json
from pathlib import Path,PurePosixPath
import queue
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation')]
from wsc import WSC,Store
from wsc.contracts import encode
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore,ResultPolicy,ToolText
from native_rpc import NativeRPC
from native_provider_frames import receive,send,loads
from native_provider_gate import ProviderGate,dispatch
from native_linux_python import command,DIRECTORY
from native_context_recovery import open_context_receiver
from native_context_session import MappedContextSession
from qualify_linux_python import checked_runtime,linux,save


class BridgeRPC(NativeRPC):
    def __init__(self,args,stderr):
        self.stderr=stderr.open('x',encoding='utf-8')
        self.proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
            text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.queue,self.pending,self.counter=queue.Queue(),[],0
        threading.Thread(target=self._reader,daemon=True).start()


def scripted_response(ordinal,item):
    response=dict(id='resp_scripted_'+str(ordinal),object='response',status='completed',
        model='fixture-no-llm',output=[item],usage=dict(input_tokens=0,output_tokens=0,total_tokens=0))
    events=[dict(type='response.created',response={**response,'status':'in_progress','output':[]}),
        dict(type='response.output_item.added',output_index=0,item=item),
        dict(type='response.output_item.done',output_index=0,item=item),
        dict(type='response.completed',response=response)]
    return ''.join('event: '+v['type']+'\ndata: '+json.dumps(v)+'\n\n' for v in events).encode()


def main(out,live=None,owner_fault=False):
    if live and owner_fault:raise ValueError('provider_trial_modes_conflict')
    state=subprocess.run(['wsl','--list','--verbose'],capture_output=True,timeout=10)
    if state.returncode or 'Running' in state.stdout.decode('utf-16-le') or 'Stopped' not in state.stdout.decode('utf-16-le'):
        raise ValueError('wsl_not_owned_stopped')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    actor=out/'actor-root';(actor/'actor').mkdir(parents=True);(actor/'home/.codex').mkdir(parents=True)
    code=actor/'bridge-code';code.mkdir()
    modules=['native_provider_frames.py','native_provider_worker.py','native_provider_actor.py','native_compaction_profile.py']
    for name in modules:shutil.copyfile(ROOT/'experiments'/name,code/name)
    runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64');python=runtime.parent/DIRECTORY
    pins=dict(native=checked_runtime(runtime),python=checked_runtime(python))
    socket_root='/tmp/wsc-provider-'+uuid4().hex
    max_calls=4 if live else 2
    base=command(linux(runtime),linux(actor),linux(python))
    base[-1:-1]=['--ro-bind',socket_root,'/run/wsc-provider']
    native=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','200' if live else '90']+base+[
        '/opt/python/bin/python3.11','-I','-B','/work/bridge-code/native_provider_actor.py','--calls',str(max_calls),
        '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    worker_command=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','200' if live else '90',
        linux(python)+'/bin/python3.11','-I','-B',linux(code/'native_provider_worker.py'),
        '--root',socket_root,'--calls',str(max_calls),'--seconds','180' if live else '80']
    source=[*sorted((ROOT/'src/wsc').rglob('*.py')),*[ROOT/'experiments'/n for n in modules],
        ROOT/'experiments/native_provider_gate.py',ROOT/'experiments/native_context_session.py',
        ROOT/'experiments/native_application_session.py',Path(__file__)]
    if live:source.extend([ROOT/'experiments/native_live_context_trial.py',ROOT/'experiments/native_provider_chatgpt.py'])
    save(private/'registration.json',dict(native=native,worker=worker_command,pins=pins,
        source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in source},
        provider='Host authenticated first-party provider' if live else 'Local scripted fixture only',
        real_model_calls=0,maximum_requests=max_calls,
        response_buffering=True,network_shared=False,credentials_loaded=False,
        registration_scope='Pre-dispatch state, not final usage'))
    if owner_fault:save(private/'fault-registration.json',dict(kind='local_owner_exception_fixture',real_model_calls=0,
        expected_http_status=502,maximum_native_error_seconds=10))
    core=WSC(Store(private/'core.db',session_id='bridge-fixture',workspace=str(actor/'actor')),access=lambda *_:True)
    ctx=ContextRuntime(core,ResultStore(private/'result-store',session='bridge-fixture'),policy=ResultPolicy(enabled=True))
    adapter=CodexCheckpointAdapter();fixture_label='Context recovery admission fixture' if live else 'Fixed scripted transport fixture'
    ctx.observe(adapter.import_items([dict(type='message',role='user',content=[dict(type='input_text',text=fixture_label)])],thread_id='fixture-history'))
    snapshot=ctx.capture()
    text=live.text if live else json.dumps({'rows':['noise-'+str(i) for i in range(7000)],'answer':{'revision':23,'status':'current'}},separators=(',',':'))
    wire=[dict(type='function_call',call_id='fixture-producer',name='fixture_data',arguments='{}'),
        dict(type='function_call_output',call_id='fixture-producer',output=text)]
    call,result=adapter.import_items(wire,thread_id='fixture-history')
    ctx.observe([call]);view=ctx.record_tool_result(result,ToolText(text,kind='json'))
    if not view.get('external'):raise ValueError('bridge_fixture_not_external')
    save(private/'original.json',loads(text));save(private/'view.json',view)
    if live:live.prepare(out,private/'registration.json',view)
    queries=dict(operation='json_pointer',reference='result:'+view['result_id'],units='json_pointer',pointer='/answer')
    port=None;session=None;rpc=None;worker=None;gate=None;owner_errors=[];owner_thread=None;callbacks=[]
    def exchange(raw):
        value=loads(raw.decode());ordinal=gate.calls
        if ordinal==1:
            outputs=[i for i in value.get('input',[]) if i.get('type')=='function_call_output' and i.get('call_id')=='fixture-producer']
            if len(outputs)!=1 or loads(outputs[0]['output'])!=view:raise ValueError('bridge_view_not_in_request')
            ctx.presented('captured-live-request-1' if live else 'captured-scripted-request-1',[result.id],receiver=port.owner)
            port.advance(ctx.capture())
        if owner_fault:raise ValueError('fixture_owner_failure')
        if live:return live.exchange(raw)
        if ordinal==1:
            item=dict(type='function_call',id='fc_scripted',call_id='scripted-query',name='WSCContext',arguments=encode(queries))
        else:
            outputs=[i for i in value.get('input',[]) if i.get('type')=='function_call_output' and i.get('call_id')=='scripted-query']
            if len(outputs)!=1:raise ValueError('bridge_recovery_output_missing')
            output=outputs[0]['output']
            if type(output) is not str:raise ValueError('bridge_recovery_output_shape')
            recovered=loads(output)
            if recovered.get('value')!={'revision':23,'status':'current'}:raise ValueError('bridge_recovery_value_changed')
            item=dict(type='message',id='msg_scripted',role='assistant',status='completed',
                content=[dict(type='output_text',text='SCRIPTED_TRANSPORT_COMPLETE',annotations=[])])
        return 200,'text/event-stream',scripted_response(ordinal,item)
    def pump():
        try:
            for ordinal in range(1,max_calls+1):
                frame=receive(worker.stdout)
                if frame.get('kind')!='request' or frame.get('ordinal')!=ordinal:raise ValueError('bridge_worker_order')
                reply,error=dispatch(gate,frame['request'],ordinal);send(worker.stdin,reply)
                if error:owner_errors.append(error);return
        except BaseException as error:owner_errors.append(dict(type=type(error).__name__,message=str(error)))
    def factory(**options):
        nonlocal rpc,session
        rpc=BridgeRPC(native,private/'native-stderr.txt')
        save(private/'initialized.json',rpc.call('initialize',dict(clientInfo=dict(name='wsc_context_recovery_admission' if live else 'wsc_scripted_bridge',version='1'),
            capabilities=dict(experimentalApi=True)),timeout=15));rpc.send(dict(method='initialized'))
        opened=rpc.call('thread/start',dict(cwd='/work/actor',model='gpt-6.1-sol',allowProviderModelFallback=False,
            approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=['/work/actor'],ephemeral=False,
            dynamicTools=options['dynamic_tools']),timeout=20)
        # Fresh native threads persist their first history asynchronously.
        # Match the existing application-session bootstrap before attachment.
        rpc.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=[dict(type='message',role='user',
            content=[dict(type='input_text',text=fixture_label)])]),timeout=10)
        path=actor/str(PurePosixPath(opened['thread']['path']).relative_to('/work'))
        deadline=time.monotonic()+3
        while not path.exists() and rpc.proc.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        session=MappedContextSession(dict(workspace='/work/actor',model='gpt-6.1-sol',effort='max'),
            private/'session',server=rpc,opened=opened,actor_root=actor,cleanup=lambda server:server.close())
        return session
    try:
        with (private/'worker-stderr.txt').open('x',encoding='utf-8') as stderr:
            worker=subprocess.Popen(worker_command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if receive(worker.stdout)!={'kind':'ready'}:raise ValueError('bridge_worker_not_ready')
        gate=ProviderGate(model='gpt-6.1-sol',max_calls=max_calls,seconds=180 if live else 75,directory=private/'requests',exchange=exchange)
        owner_thread=threading.Thread(target=pump,daemon=True);owner_thread.start()
        port=open_context_receiver(factory,ctx,snapshot,actor_root=actor)
        rpc.call('thread/inject_items',dict(threadId=port.owner,items=[wire[0],{**wire[1],'output':encode(view)}]),timeout=10)
        params=dict(threadId=port.owner,model='gpt-6.1-sol',effort='max',
            input=[dict(type='text',text=live.request if live else 'Scripted transport fixture.')])
        if live:params['outputSchema']=live.schema
        turn_begin=time.perf_counter()
        started=rpc.call('turn/start',params,timeout=15)
        turn=started['turn']['id'];deadline=time.monotonic()+(160 if live else 50);completed=False
        while time.monotonic()<deadline:
            try:event=rpc.event(timeout=.5)
            except queue.Empty:continue
            with (private/'events.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps(event)+'\n')
            if event.get('method')=='item/tool/call':
                reply=port.handler.handle(event,thread_id=port.owner,turn_id=turn)
                callbacks.append(dict(event=event,reply=reply,origin='Actual model via native client' if live else 'Native client from scripted provider, not an LLM'))
                rpc.send(reply)
            if event.get('method')=='error':
                if owner_fault:
                    elapsed=time.perf_counter()-turn_begin
                    status=event['params']['error'].get('codexErrorInfo',{}).get('httpConnectionFailed',{}).get('httpStatusCode')
                    if status!=502 or gate.calls!=1 or not owner_errors or elapsed>=10:
                        raise ValueError('bridge_error_return_unqualified')
                    save(out/'results.json',dict(real_model_calls=0,owner_fixture_requests=1,native_error_http_status=status,
                        native_error_seconds=elapsed,owner_error_return_verified=True,no_retry=True,
                        scope='Actual native client with local owner exception; no live provider or task quality result'))
                    print(json.dumps(json.loads((out/'results.json').read_text())))
                    return
                raise ValueError('bridge_native_error')
            if event.get('method')=='turn/completed':
                completed=event['params']['turn']['status']=='completed';break
        if live:
            outcome=live.finish(callbacks,failure=None if completed and not owner_errors else 'native_cycle_incomplete')
            save(private/'callbacks.json',callbacks);save(private/'gate-trace.json',gate.trace)
            save(out/'results.json',outcome);print(json.dumps({k:outcome[k] for k in ['success','real_model_calls_attempted','known_response_receipts','usage_complete','exact_answer_and_reference','actual_callbacks','failure']}))
            return
        if not completed or len(callbacks)!=1 or gate.calls!=2 or owner_errors:raise ValueError('bridge_native_cycle_incomplete')
        owner_thread.join(timeout=3);worker.wait(timeout=3)
        probe='''import json,sys,urllib.request,urllib.error
for path in sys.argv[1:]:
 try:
  with open(path,'rb') as f:f.read(1)
 except OSError: pass
 else: raise AssertionError('private file readable')
with open('/work/provider-transport.json') as f:binding=json.load(f)
request=urllib.request.Request(binding['base_url']+'/responses',data=b'{"model":"gpt-6.1-sol"}',headers={'Content-Type':'application/json'})
try: urllib.request.urlopen(request,timeout=3)
except urllib.error.HTTPError as error:
 assert error.code==429,error.code
else: raise AssertionError('third request admitted')
print(json.dumps({'private_unreadable':True,'third_request_status':429}))
'''
        probe_paths=[linux(private/'core.db'),'/proc/1/root'+linux(private/'core.db'),
            linux(private/'result-store/results.sqlite3')]
        observed=rpc.call('command/exec',dict(command=['/opt/python/bin/python3.11','-I','-B','-c',probe,*probe_paths],
            cwd='/work/actor',sandboxPolicy=dict(type='readOnly',networkAccess=True),timeoutMs=10000),timeout=15)
        save(private/'boundary-probe.json',dict(paths=probe_paths,response=observed,
            network_scope='Only the outer isolated network namespace; no host or external network'))
        if observed.get('exitCode')!=0 or loads(observed['stdout'])!={'private_unreadable':True,'third_request_status':429}:
            raise ValueError('bridge_boundary_probe_failed')
        save(private/'callbacks.json',callbacks);save(private/'gate-trace.json',gate.trace)
        save(out/'results.json',dict(real_model_calls=0,scripted_provider_requests=2,
            actual_native_request_view_verified=True,actual_native_dynamic_callback_verified=True,
            actual_native_next_request_recovery_verified=True,original_bytes=len(text.encode()),view_bytes=len(encode(view).encode()),
            base_filesystem_policy_retained=True,private_canary_unreadable=True,third_request_rejected=True,
            actual_model_recovery_verified=False,paid_dispatch_admitted=False,
            scope='Native transport with scripted Responses; not model quality or token savings'))
        print(json.dumps(json.loads((out/'results.json').read_text())))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),owner_errors=owner_errors,
            real_model_calls_attempted=live.network_attempts if live else 0));raise
    finally:
        if live:
            try:
                if not live.settled and live.ledger:live.finish(callbacks,failure='execution_failed_or_incomplete')
            except BaseException as error:
                save(out/'budget-error.json',dict(type=type(error).__name__,error=str(error)))
            finally:
                try:live.close()
                except BaseException as error:save(out/'budget-close-error.json',dict(type=type(error).__name__))
        if gate and not (private/'gate-trace.json').exists():save(private/'gate-trace.json',gate.trace)
        if callbacks and not (private/'callbacks.json').exists():save(private/'callbacks.json',callbacks)
        if rpc and rpc.proc.stdin and not rpc.proc.stdin.closed:rpc.proc.stdin.close()
        if worker and worker.stdin and not worker.stdin.closed:worker.stdin.close()
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))
        for process in ([rpc.proc] if rpc else [])+([worker] if worker else []):process.wait(timeout=5)
        if rpc:rpc.proc.stdout.close();rpc.stderr.close()
        if worker:worker.stdout.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--owned-wsl-distribution',action='store_true',required=True)
    p.add_argument('--live-first-party',action='store_true')
    p.add_argument('--owner-failure-fixture',action='store_true')
    p.add_argument('--live-revision',type=int,choices=(1,2),default=1)
    a=p.parse_args()
    if a.live_first_party:
        from native_live_context_trial import LiveContextTrial
        main(a.out.resolve(),live=LiveContextTrial(revision=a.live_revision),owner_fault=a.owner_failure_fixture)
    else:main(a.out.resolve(),owner_fault=a.owner_failure_fixture)
