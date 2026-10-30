"""Zero-model Linux protocol probe, not an isolated or paid benchmark actor.

The caller owns the docker-desktop WSL distribution for this probe. Cleanup
terminates that distribution; use only after its initial stopped state is known.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import queue
import subprocess
import sys
import threading
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_rpc import NativeRPC
from native_source_tool import SOURCE_TOOL
from native_linux_envelope import command as envelope_command,POLICY

ALLOWED={'initialize','initialized','thread/start','thread/inject_items','command/exec'}


class ProbeRPC(NativeRPC):
    def __init__(self, command, stderr_path):
        self.stderr=stderr_path.open('x',encoding='utf-8')
        self.proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,
             text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.queue,self.pending,self.counter=queue.Queue(),[],0
        self.sent=[]
        threading.Thread(target=self._reader,daemon=True).start()

    def send(self,value):
        if value.get('method') not in ALLOWED:raise ValueError('linux_probe_method_not_admitted')
        self.sent.append(value['method']);super().send(value)


def save(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def main(out,filesystem_envelope=False,private_inventory=None):
    out.mkdir(parents=True,exist_ok=False)
    home='/tmp/wsc-native-probe-'+uuid4().hex
    work=home+'/actor'
    binary='/mnt/host/d/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64/bin/codex'
    wsl=['wsl','--distribution','docker-desktop','--exec']
    # Empty environment and home: no host auth, global plugins or MCP services.
    command=wsl+['/usr/bin/timeout','40','/usr/bin/unshare','-n','--','/usr/bin/env','-i',
       'PATH=/usr/local/bin:/usr/bin:/bin','HOME='+home,'CODEX_HOME='+home+'/.codex',
       binary,'app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    actor_root=None
    private_paths=[];private_files={}
    if private_inventory is not None:
        if not filesystem_envelope:raise ValueError('linux_probe_private_inventory_requires_envelope')
        for value in json.loads(private_inventory.read_text(encoding='utf-8'))['files']:
            source=Path(value).resolve(strict=True)
            if not source.is_file():raise ValueError('linux_probe_private_source_missing')
            private_files[str(source)]=sha256(source.read_bytes()).hexdigest()
            suffix=source.drive[0].lower()+'/'+source.as_posix().split(':/',1)[1]
            private_paths.extend(['/mnt/host/'+suffix,'/proc/1/root/mnt/host/'+suffix])
    if filesystem_envelope:
        actor_root=out/'actor-root';actor_root.mkdir()
        home='/work/home';work='/work/actor'
        linux_root='/mnt/host/'+actor_root.drive[0].lower()+'/'+actor_root.as_posix().split(':/',1)[1]
        (actor_root/'home/.codex').mkdir(parents=True);(actor_root/'actor').mkdir()
        command=wsl+['/usr/bin/timeout','40']+envelope_command(str(PurePosixPath(binary).parent.parent),linux_root)+[
          '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    save(out/'registration.json',dict(command=command,home=home,workspace=work,
         model='gpt-6.1-sol',effort='max',allowed_methods=sorted(ALLOWED),
         model_calls=0,filesystem_policy=POLICY if filesystem_envelope else None,
         private_inventory=str(private_inventory) if private_inventory else None,private_files_sha256=private_files,
         scope='Offline protocol/mount probe only; provider and model behavior unqualified',
         cleanup='Caller-owned docker-desktop WSL distribution terminated'))
    rpc=None
    result=dict(native_version='0.165.0-alpha.1.2',protocol_qualified=False,model_requests_issued=0,
                private_boundary_qualified=False,paid_dispatch_admitted=False)
    try:
        if not filesystem_envelope:
            subprocess.run(wsl+['/bin/mkdir','-p',home+'/.codex',work],capture_output=True,check=True,timeout=10)
        rpc=ProbeRPC(command,out/'stderr.txt')
        initialized=rpc.call('initialize',dict(clientInfo=dict(name='wsc_linux_protocol_probe',version='1'),
                              capabilities=dict(experimentalApi=True)),timeout=15)
        save(out/'initialized.json',initialized);rpc.send(dict(method='initialized'))
        opened=rpc.call('thread/start',dict(cwd=work,model='gpt-6.1-sol',allowProviderModelFallback=False,
                       approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=[work],
                       ephemeral=False,dynamicTools=[SOURCE_TOOL]),timeout=20)
        save(out/'opened.json',opened)
        if opened['model']!='gpt-6.1-sol' or opened['reasoningEffort']!='max':raise ValueError('linux_probe_model_changed')
        items=[dict(type='message',role='assistant',content=[dict(type='output_text',text='{"record_type":"wsc.protocol_probe/1","source_count":2}')])]
        imported=rpc.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=items),timeout=10)
        save(out/'injected.json',imported)
        result.update(initialization=True,thread_started=True,dynamic_source_tool_registered=True)
        path=PurePosixPath(opened['thread']['path'])
        if not path.is_relative_to(PurePosixPath(home)):raise ValueError('linux_probe_history_outside_owned_home')
        raw=((actor_root/str(path.relative_to('/work'))).read_bytes() if filesystem_envelope else
             subprocess.run(wsl+['/bin/cat',str(path)],capture_output=True,check=True,timeout=10).stdout)
        rows=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
        if any(row['type']=='token_usage_record' for row in rows):raise ValueError('linux_probe_unexpected_model_usage')
        if not any(row.get('type')=='response_item' and row.get('payload',{}).get('role')=='assistant'
                   and row['payload'].get('content')==items[0]['content'] for row in rows):
            raise ValueError('linux_probe_import_not_observed')
        (out/'rollout.jsonl').write_bytes(raw)
        result['history_import_verified']=True
        response=rpc.call('command/exec',dict(command=['/bin/sh','-c','printf wsc-native-tool-probe'],
                         cwd=work,timeoutMs=5000),timeout=10)
        save(out/'command.json',response)
        if response.get('exitCode')!=0 or response.get('stdout')!='wsc-native-tool-probe':
            raise ValueError('linux_probe_native_command_failed')
        result.update(protocol_qualified=True,command_exec=True)
        if filesystem_envelope:
            candidates=['/mnt/host/d/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7/A/migrate.py',
                '/proc/1/root/mnt/host/d/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7/A/migrate.py',
                '/run/desktop/mnt/host/d/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7/A/migrate.py',
                '/var/run/docker.sock']
            candidates=list(dict.fromkeys(candidates+private_paths))
            script='for p in "$@"; do if cat "$p" >/dev/null 2>&1; then exit 1; fi; done; printf private-files-unreadable'
            response=rpc.call('command/exec',dict(command=['/bin/sh','-c',script,'probe',*candidates],cwd=work,timeoutMs=5000),timeout=10)
            save(out/'private-read-probe.json',dict(paths=candidates,response=response))
            if response.get('exitCode')!=0 or response.get('stdout')!='private-files-unreadable':
                raise ValueError('linux_envelope_private_read_failed')
            result.update(declared_private_paths_unreadable=True,filesystem_policy=POLICY,
                          private_files_present_on_host=len(private_files),private_path_forms_tested=len(candidates),
                          private_boundary_scope='Declared paths via actual native command/exec; no model or network claim')
    except BaseException as error:
        result.update(error_type=type(error).__name__,error=str(error))
    finally:
        if rpc:
            save(out/'methods-issued.json',dict(methods=rpc.sent,model_requests_issued=0))
            if rpc.proc.stdin:rpc.proc.stdin.close()
        # WSL was started solely for this bounded probe. Do not leave Linux
        # descendants or a persistent daemon behind after a failed RPC.
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode,stdout_hex=cleanup.stdout.hex(),stderr_hex=cleanup.stderr.hex()))
        if rpc:
            rpc.proc.wait(timeout=5);rpc.proc.stdout.close();rpc.stderr.close()
        if cleanup.returncode:result['cleanup_failed']=True
        save(out/'results.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--owned-wsl-distribution',required=True,action='store_true')
    parser.add_argument('--filesystem-envelope',action='store_true')
    parser.add_argument('--private-inventory',type=Path)
    args=parser.parse_args();main(args.out.resolve(),args.filesystem_envelope,args.private_inventory)
