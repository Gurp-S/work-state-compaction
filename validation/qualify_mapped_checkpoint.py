"""Reuse a sealed model draft; qualify native installation/restart with no LLM."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation')]
from wsc import WSC,Store,Event,Selection,Understanding
from wsc.contracts import digest,encode
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultStore
from native_context_recovery import open_context_receiver
from native_context_session import MappedContextSession
from native_mapped_checkpoint_host import MappedCheckpointHost
from native_evidence import state
from native_rollout_snapshot import parse_rollout
from native_linux_python import command,DIRECTORY
from qualify_linux_python import checked_runtime,linux,save
from qualify_native_provider_bridge import BridgeRPC


class OfflineRPC(BridgeRPC):
    def __init__(self,*args):self.methods=[];self.injected=[];super().__init__(*args)
    def send(self,value):
        method=value.get('method')
        if method not in {'initialize','initialized','thread/start','thread/resume','thread/inject_items','command/exec'}:
            raise ValueError('checkpoint_probe_method_not_admitted')
        self.methods.append(method)
        if method=='thread/inject_items':self.injected.append(digest(value['params']['items']))
        super().send(value)


def main(out):
    status=subprocess.run(['wsl','--list','--verbose'],capture_output=True,timeout=10)
    if status.returncode or 'Running' in status.stdout.decode('utf-16-le') or 'Stopped' not in status.stdout.decode('utf-16-le'):
        raise ValueError('wsl_not_owned_stopped')
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    actor=out/'actor-root';(actor/'actor').mkdir(parents=True);(actor/'home/.codex').mkdir(parents=True)
    old=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1/coordinator-private/C')
    old_publication=json.loads((old/'publication.json').read_bytes());cut=old_publication['package']['binding']['cut']
    source_hash=sha256((old/'state.db').read_bytes()).hexdigest()
    with sqlite3.connect((old/'state.db').as_uri()+'?mode=ro',uri=True) as db:
        rows=db.execute('SELECT seq,data,digest FROM events WHERE seq<=? ORDER BY seq',(cut,)).fetchall()
    events=[]
    for seq,raw,h in rows:
        if sha256(raw.encode()).hexdigest()!=h:raise ValueError('legacy_source_integrity_changed')
        events.append(Event(**json.loads(raw)))
    draft=json.loads(json.loads((old/'selection/phase-outcome.json').read_bytes())['finals'][-1]['text'])
    aliases={'s'+str(seq):event.id for (seq,_,_),event in zip(rows,events)}
    def ids(values):return tuple(aliases[v] for v in values)
    if draft['span_refs'] or draft['retained_excerpt_keys'] or draft['understanding_refs']:
        raise ValueError('legacy_draft_reuse_frontend_not_supported')
    selection=Selection(source_ids=ids(draft['source_ids']),
        new_understandings=tuple(Understanding(**{**v,'sources':ids(v['sources'])}) for v in draft['new_understandings']),
        clues=tuple({**v,'sources':list(ids(v['sources']))} for v in draft['clues']))
    denied=set();session_id='mapped-reuse-'+uuid4().hex
    def context():
        return ContextRuntime(WSC(Store(private/'core.db',session_id=session_id,workspace=str(actor/'actor')),
            access=lambda s,i,o:i not in denied),ResultStore(private/'results',session=session_id))
    ctx=context();ctx.observe(events)
    ctx.presented('offline-draft-reuse',[e.id for e in events],receiver='offline-not-model-request')
    snapshot=ctx.capture()
    if snapshot.source_digest!=old_publication['package']['binding']['source_digest']:
        raise ValueError('legacy_source_digest_not_exact')
    view=ctx.prepare(snapshot,selection,producer='historical-model-draft-reuse-no-new-model')
    operation=ctx.stage(view,directory=private/'exports');package=ctx.core.package(operation)
    runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64');python=runtime.parent/DIRECTORY
    args=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','90']+command(linux(runtime),linux(actor),linux(python))+[
        '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    sources=[*sorted((ROOT/'src/wsc').rglob('*.py')),ROOT/'experiments/native_mapped_checkpoint_host.py',
        ROOT/'experiments/native_context_recovery.py',ROOT/'experiments/native_context_session.py',Path(__file__)]
    save(private/'registration.json',dict(model_calls=0,reused_selection=str(old/'selection/phase-outcome.json'),
        reused_draft_sha256=digest(draft),legacy_database_sha256=source_hash,old_source_digest=snapshot.source_digest,
        new_workspace=str(actor/'actor'),operation_id=operation,package_digest=package['package_digest'],
        runtime=dict(native=checked_runtime(runtime),python=checked_runtime(python)),
        source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in sources},
        scope='Actual native checkpoint transport/restart only; no model continuity or quality result'))
    servers=[];sessions=[];owner=None;bootstrap=None;faults=[]
    def factory(**options):
        nonlocal owner,bootstrap
        index=len(servers);rpc=OfflineRPC(args,private/f'native-{index}-stderr.txt');servers.append(rpc)
        rpc.call('initialize',dict(clientInfo=dict(name='wsc_mapped_checkpoint',version='1'),capabilities=dict(experimentalApi=True)),timeout=15)
        rpc.send(dict(method='initialized'))
        params=dict(cwd='/work/actor',model='gpt-6.1-sol',approvalPolicy='never',sandbox='read-only')
        if owner is None:
            opened=rpc.call('thread/start',dict(**params,allowProviderModelFallback=False,runtimeWorkspaceRoots=['/work/actor'],
                ephemeral=False,dynamicTools=options['dynamic_tools']),timeout=20)
            owner=opened['thread']['id']
            rpc.call('thread/inject_items',dict(threadId=owner,items=[dict(type='message',role='user',
                content=[dict(type='input_text',text='Native checkpoint protocol fixture')])]),timeout=10)
        else:opened=rpc.call('thread/resume',dict(**params,threadId=owner),timeout=20)
        session=MappedContextSession(dict(workspace='/work/actor',model='gpt-6.1-sol',effort='max'),
            private/f'session-{index}',server=rpc,opened=opened,actor_root=actor,cleanup=lambda server:server.close())
        sessions.append(session)
        if index==0:bootstrap=state(parse_rollout(session.rollout_path().read_bytes()).rows)
        return session
    try:
        port=open_context_receiver(factory,ctx,ctx.capture(),actor_root=actor)
        def lost():faults.append('after-native-persist-before-receipt');raise TimeoutError('injected_host_reply_loss')
        host=MappedCheckpointHost(port,private/'host-journal',bootstrap=bootstrap,after_import=lost)
        try:ctx.install(operation,host)
        except TimeoutError:pass
        else:raise ValueError('checkpoint_fault_not_observed')
        if len(faults)!=1 or ctx.core.status()['cursor']!=0:raise ValueError('checkpoint_advanced_without_receipt')
        tail=dict(type='message',role='user',content=[dict(type='input_text',text='{"record_type":"later_native_tail/1","preserved":true}')])
        servers[0].call('thread/inject_items',dict(threadId=owner,items=[tail]),timeout=10)
        sessions[0].close()
        ctx=context();denied.add(events[44].id)
        resumed=open_context_receiver(factory,ctx,ctx.capture(),actor_root=actor)
        recovered=MappedCheckpointHost(resumed,private/'host-journal')
        ctx.reconcile(operation,recovered)
        if ctx.core.status()['cursor']!=cut or ctx.core.status()['generation']!=1:raise ValueError('checkpoint_reconcile_not_confirmed')
        query=dict(operation='read',reference='source:s45',units='unicode_codepoints',offset=0,limit=4096)
        blocked=ctx.query_tool(ctx.capture()).call(query)
        if blocked.status!='error':raise ValueError('checkpoint_revoked_source_readable')
        denied.clear();value=ctx.query_tool(ctx.capture()).query(query)
        if value['text']!=events[44].text:raise ValueError('checkpoint_old_source_not_exact')
        ctx.install(operation,recovered)
        raw=sessions[-1].rollout_path().read_bytes();actual=state(parse_rollout(raw).rows)
        if not any(v.get('content')==tail['content'] and v.get('role')=='user' for v in actual):raise ValueError('checkpoint_tail_lost')
        injected=sum(s.injected.count(digest(package['items'])) for s in servers)
        if injected!=1:raise ValueError('checkpoint_replayed')
        if sha256((old/'state.db').read_bytes()).hexdigest()!=source_hash:raise ValueError('legacy_store_mutated')
        (private/'resumed-native-rollout.jsonl').write_bytes(raw)
        save(private/'query-proof.json',dict(revoked_status=blocked.status,restored=value,source_text_sha256=sha256(events[44].text.encode()).hexdigest()))
        save(out/'results.json',dict(model_calls=0,legacy_draft_reused=True,source_bytes_unchanged=True,
            actual_native_install_observed=True,reply_and_receipt_loss_recovered=True,native_process_restarted=True,
            native_thread_resumed=True,checkpoint_injections=injected,later_native_tail_preserved=True,
            revoked_source_denied=True,old_source_recovered_exactly=True,generation=1,cursor=cut,
            actual_model_after_resume_tool_registration_verified=False,paid_dispatch_admitted=False))
        print(json.dumps(json.loads((out/'results.json').read_bytes())))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error),model_calls=0));raise
    finally:
        save(private/'methods-issued.json',dict(servers=[s.methods for s in servers],faults=faults,model_calls=0))
        for session in sessions:
            if not session.closed:
                try:session.close()
                except Exception:pass
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--owned-wsl-distribution',action='store_true',required=True)
    main(p.parse_args().out.resolve())
