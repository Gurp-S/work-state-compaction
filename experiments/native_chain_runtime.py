"""Common closed-mount runtime factory; owner cleanup is shared by the batch.

No auth loading, budget creation, oracle copying, retries or automatic dispatch.
"""
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from uuid import uuid4

from native_chain_gateway import ChainGateway,PhaseBoundSession
from native_compaction_profile import PROFILE
from native_context_session import MappedContextSession
from native_linux_python import command
from native_measured_chain import measured_provider,MeasuredSession
from native_provider_frames import receive,send
from native_provider_gate import dispatch
from native_rpc import NativeRPC
from native_evidence import save

ROOT=Path(__file__).resolve().parent


def linux(path):
    value=Path(path).resolve().as_posix()
    if len(value)<4 or value[1:3]!=':/':raise ValueError('chain_runtime_windows_path_required')
    return '/mnt/host/'+value[0].lower()+value[2:]


class _RPC(NativeRPC):
    def __init__(self,args,stderr):
        self.stderr=stderr.open('x',encoding='utf-8')
        self.proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
            text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.queue,self.pending,self.counter=queue.Queue(),[],0
        threading.Thread(target=self._reader,daemon=True).start()


class RuntimeOwner:
    """One batch owns a previously stopped distribution, not each parallel arm."""
    def __init__(self,*,owned_distribution):
        if owned_distribution!='docker-desktop':raise ValueError('chain_distribution_unregistered')
        state=subprocess.run(['wsl','--list','--verbose'],capture_output=True,timeout=10)
        text=state.stdout.decode('utf-16-le')
        if state.returncode or 'Running' in text or 'Stopped' not in text:raise ValueError('chain_distribution_not_owned_stopped')
        self.distribution=owned_distribution;self.factories=[];self.closed=False
    def register(self,factory):
        if self.closed:raise ValueError('chain_runtime_owner_closed')
        self.factories.append(factory)
    def close(self):
        if self.closed:return dict(closed=True)
        errors=[]
        for factory in self.factories:
            try:factory.close()
            except Exception as error:errors.append(type(error).__name__)
        # Exactly once after all owned arm cleanup attempts, never inside an arm.
        result=subprocess.run(['wsl','--terminate',self.distribution],capture_output=True,timeout=15)
        self.closed=result.returncode==0 and not errors
        return dict(closed=self.closed,distribution_stopped=result.returncode==0,exit_code=result.returncode,per_arm_cleanup_errors=errors)


class ChainRuntimeFactory:
    def __init__(self,owner,directory,*,runtime,python,model,effort,max_calls,lifetime_seconds,
                 exchange,timing,verify_runtime,starter_files):
        if type(max_calls) is not int or not 1<=max_calls<=64 or type(lifetime_seconds) is not int or not 1<=lifetime_seconds<=3600:
            raise ValueError('chain_runtime_limits_invalid')
        if not callable(exchange) or not callable(verify_runtime):raise ValueError('chain_runtime_callbacks_missing')
        if set(starter_files) not in ({'retry_client.py','test_smoke.py'},{'migrate.py','test_smoke.py'}):
            raise ValueError('chain_runtime_starter_invalid')
        self.owner,self.directory=owner,Path(directory)
        self.runtime,self.python,self.model,self.effort=Path(runtime),Path(python),model,effort
        self.max_calls,self.lifetime=max_calls,lifetime_seconds
        self.exchange,self.timing,self.verify=exchange,timing,verify_runtime
        self.starter_files=starter_files
        self.rpc=self.worker=self.session=None;self.worker_stderr=None;self.pump=None
        self.errors=[];self.gateway=None;self.used=False;self.cleanup_serial=0;owner.register(self)

    def open_with_history(self,initial_history,remaining):
        return self(remaining,initial_history=initial_history)

    def __call__(self,remaining,*,initial_history=None):
        if type(initial_history) is not list or not initial_history:raise ValueError('chain_runtime_initial_history_required')
        if self.used:raise ValueError('chain_runtime_factory_no_replay')
        self.used=True;remaining();pins=self.verify(self.runtime,self.python)
        self.directory.mkdir(parents=True,exist_ok=False)
        actor=self.directory/'actor-root';(actor/'actor').mkdir(parents=True);(actor/'home/.codex').mkdir(parents=True)
        for name,source in self.starter_files.items():
            with Path(source).open('rb') as stream:raw=stream.read(1048577)
            if len(raw)>1048576:raise ValueError('chain_runtime_starter_size_exceeded')
            (actor/'actor'/name).write_bytes(raw)
        code=actor/'bridge-code';code.mkdir()
        for name in ('native_provider_frames.py','native_provider_actor.py','native_compaction_profile.py','native_chain_worker.py'):
            shutil.copyfile(ROOT/name,code/name)
        socket_root='/tmp/wsc-provider-'+uuid4().hex
        prefix=['wsl','--distribution',self.owner.distribution,'--exec','/usr/bin/timeout',str(self.lifetime+30)]
        worker=prefix+[linux(self.python)+'/bin/python3.11','-I','-B',linux(code/'native_chain_worker.py'),
            '--root',socket_root,'--calls',str(self.max_calls),'--seconds',str(self.lifetime)]
        base=command(linux(self.runtime),linux(actor),linux(self.python));base[-1:-1]=['--ro-bind',socket_root,'/run/wsc-provider']
        native=prefix+base+['/opt/python/bin/python3.11','-I','-B','/work/bridge-code/native_provider_actor.py',
            '--calls',str(self.max_calls),'--compaction-v2','/opt/codex/bin/codex','app-server','--stdio',
            '-c','features.multi_agent=false','-c','model_reasoning_effort="'+self.effort+'"']
        save(self.directory/'runtime-binding.json',dict(pins=pins,native=native,worker=worker,profile=PROFILE))
        try:
            self.worker_stderr=(self.directory/'worker-stderr.txt').open('x',encoding='utf-8')
            self.worker=subprocess.Popen(worker,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.worker_stderr,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            ready=receive(self.worker.stdout)
            if ready.get('kind')!='ready' or ready.get('lifetime_seconds')!=self.lifetime:raise ValueError('chain_worker_unready')
            save(self.directory/'worker-ready.json',ready)
            self.gateway=ChainGateway(model=self.model,max_calls=self.max_calls,directory=self.directory/'requests',
                                      exchange=measured_provider(self.exchange,self.timing))
            def pump():
                try:
                    for ordinal in range(1,self.max_calls+1):
                        frame=receive(self.worker.stdout)
                        if frame.get('kind')!='request' or frame.get('ordinal')!=ordinal:raise ValueError('chain_worker_request_order')
                        reply,error=dispatch(self.gateway,frame['request'],ordinal);send(self.worker.stdin,reply)
                        if error:self.errors.append(error)
                except EOFError:pass
                except Exception as error:self.errors.append(dict(type=type(error).__name__,code=str(error)))
            self.pump=threading.Thread(target=pump,daemon=True);self.pump.start()
            self.rpc=_RPC(native,self.directory/'native-stderr.txt')
            self.rpc.call('initialize',dict(clientInfo=dict(name='wsc_chain_runtime',version='1'),
                          capabilities=dict(experimentalApi=True)),timeout=min(15,remaining()['max_seconds']))
            self.rpc.send(dict(method='initialized'))
            opened=self.rpc.call('thread/start',dict(cwd='/work/actor',model=self.model,allowProviderModelFallback=False,
                approvalPolicy='never',sandbox='danger-full-access',runtimeWorkspaceRoots=['/work/actor'],ephemeral=False,dynamicTools=[]),
                timeout=min(20,remaining()['max_seconds']))
            from pathlib import PurePosixPath
            history=actor/str(PurePosixPath(opened['thread']['path']).relative_to('/work'))
            self.rpc.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=initial_history),
                          timeout=min(15,remaining()['max_seconds']))
            deadline=time.monotonic()+min(3,remaining()['max_seconds'])
            while not history.exists() and time.monotonic()<deadline:time.sleep(.02)
            from native_chain_compaction import bounded
            from native_rollout_snapshot import parse_rollout
            from native_evidence import state,import_evidence,digest
            raw=bounded(history,32*1024*1024);parsed=parse_rollout(raw)
            imported=import_evidence(state(parsed.rows),initial_history)
            if (not parsed.metadata['parse_complete'] or not imported['matched']
                    or imported['start_ordinal']+len(initial_history)!=len(state(parsed.rows))
                    or any(row['type']=='token_usage_record' for row in parsed.rows)):
                raise ValueError('chain_runtime_initial_import_unverified')
            initial_proof=dict(items_sha256=digest(initial_history),import_evidence=imported,history_sha256=parsed.metadata['sha256'])
            save(self.directory/'initial-import.json',initial_proof)
            actual=MappedContextSession(dict(workspace='/work/actor',model=self.model,effort=self.effort,native_compaction_profile=PROFILE),
                self.directory/'session',server=self.rpc,opened=opened,actor_root=actor,cleanup=lambda server:self._close_processes())
            self.session=actual
            actual.chain_initial_import=initial_proof
            return MeasuredSession(PhaseBoundSession(actual,self.gateway),self.timing)
        except BaseException:
            self._close_processes();raise

    def _close_processes(self):
        self.cleanup_serial+=1
        errors=[]
        try:
            if self.rpc and self.rpc.proc.poll() is None:self.rpc.close()
        except Exception as error:errors.append(type(error).__name__)
        try:
            if self.worker:
                if self.worker.stdin and not self.worker.stdin.closed:self.worker.stdin.close()
                self.worker.wait(timeout=5)
                if self.worker.stdout:self.worker.stdout.close()
            if self.pump:self.pump.join(timeout=2)
            if self.pump and self.pump.is_alive():raise RuntimeError('chain_provider_pump_still_live')
            if self.worker_stderr:self.worker_stderr.close()
        except Exception as error:errors.append(type(error).__name__)
        if self.gateway:save(self.directory/('gateway-trace-'+str(self.cleanup_serial)+'.json'),dict(trace=self.gateway.trace,errors=self.errors))
        if errors:raise RuntimeError('chain_runtime_cleanup_unconfirmed:'+','.join(errors))
        return dict(closed=True)
    def close(self):
        if self.session and not self.session.closed:return self.session.close()
        return self._close_processes()
