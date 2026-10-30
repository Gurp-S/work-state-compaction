"""One parent-budgeted real native V2 compaction, with opaque outcome evidence."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'validation'),
    str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.campaign_allocation import remaining
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from native_context_session import MappedContextSession
from native_provider_chatgpt import ChatGPTProvider
from native_provider_gate import ProviderGate,dispatch
from native_provider_frames import receive,send
from native_compaction_profile import PROFILE
from native_linux_python import command,DIRECTORY
from native_evidence import state
from native_rollout_snapshot import parse_rollout
from blackbox import compression_evidence
from qualify_native_provider_bridge import BridgeRPC
from qualify_linux_python import checked_runtime,linux,save

PARENT=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1')
PARENT_SHA='cbf8bc5592dd873ab2394ea2b9f2e2f322c77b4d55c9c1498cd6f0749dab41af'
LIMITS=dict(max_total_tokens=80000,max_responses=1,max_seconds=180)


def main(out):
    status=subprocess.run(['wsl','--list','--verbose'],capture_output=True,timeout=10)
    if status.returncode or 'Running' in status.stdout.decode('utf-16-le') or 'Stopped' not in status.stdout.decode('utf-16-le'):
        raise ValueError('wsl_not_owned_stopped')
    envelope=PARENT/'next-admission-envelope.json'
    if sha256(envelope.read_bytes()).hexdigest()!=PARENT_SHA:raise ValueError('compaction_parent_changed')
    claim=PARENT/'matrix-native-v2-compaction-20261030.claim.json'
    if claim.exists():raise ValueError('native_compaction_admission_already_claimed')
    claims=sorted(PARENT.glob('matrix-*.claim.json'))
    before_allocation=remaining(json.loads(envelope.read_bytes())['remaining_limits'],[json.loads(p.read_bytes())['limits'] for p in claims])
    after_allocation=remaining(before_allocation,[LIMITS])
    out.mkdir(parents=True,exist_ok=False);private=out/'coordinator-private';private.mkdir()
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    provider=ChatGPTProvider(home/'auth.json',timeout=90,capture_directory=private/'provider-responses')
    provider._headers()  # Expiry/format preflight only; never log returned headers.
    actor=out/'actor-root';(actor/'actor').mkdir(parents=True);(actor/'home/.codex').mkdir(parents=True)
    code=actor/'bridge-code';code.mkdir()
    modules=['native_provider_frames.py','native_provider_worker.py','native_provider_actor.py','native_compaction_profile.py']
    for name in modules:shutil.copyfile(ROOT/'experiments'/name,code/name)
    runtime=Path('D:/agent-task-runs/wsc-tools/codex-0.165.0-alpha.1.2-linux-x64');python=runtime.parent/DIRECTORY
    socket_root='/tmp/wsc-provider-'+uuid4().hex
    base=command(linux(runtime),linux(actor),linux(python));base[-1:-1]=['--ro-bind',socket_root,'/run/wsc-provider']
    args=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','200']+base+[
        '/opt/python/bin/python3.11','-I','-B','/work/bridge-code/native_provider_actor.py','--calls','1','--compaction-v2',
        '/opt/codex/bin/codex','app-server','--stdio','-c','features.multi_agent=false','-c','model_reasoning_effort="max"']
    worker_args=['wsl','--distribution','docker-desktop','--exec','/usr/bin/timeout','200',
        linux(python)+'/bin/python3.11','-I','-B',linux(code/'native_provider_worker.py'),
        '--root',socket_root,'--calls','1','--seconds','180']
    history_path=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1/coordinator-private/inputs.json')
    prefix=json.loads(history_path.read_bytes())['prefix']
    sources=[ROOT/'experiments'/p for p in [*modules,'native_provider_gate.py','native_provider_chatgpt.py',
        'native_context_session.py','native_application_session.py','native_turn_accounting.py']]+[Path(__file__)]
    registration=dict(kind='actual_native_remote_v2_compaction_admission_not_BC',profile=PROFILE,
        model='gpt-6.1-sol',effort='max',temperature=None,seed=None,capacity='unobserved; system blackbox',limits=LIMITS,
        max_upstream_requests=1,no_retry=True,old_failures_and_unknowns_preserved=True,
        allocation_before=before_allocation,allocation_after=after_allocation,parent_sha256=PARENT_SHA,
        prior_claim_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in claims},
        history_path=str(history_path),history_file_sha256=sha256(history_path.read_bytes()).hexdigest(),
        source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in sources},
        runtime=dict(native=checked_runtime(runtime),python=checked_runtime(python)),
        outcome_gate='Native terminal + bound compaction receipt + durable compacted boundary + opaque item type; no summary semantics scoring',
        token_policy='Response-boundary; overshoot retained, not a provider hard cap',
        summary_content_inspected=False,request_raw_bytes_rewritten=False,credentials_archived=False)
    save(private/'registration.json',registration)
    save(claim,dict(child=str(out),limits=LIMITS,parent_sha256=PARENT_SHA,
        registration_sha256=sha256((private/'registration.json').read_bytes()).hexdigest(),allocation_is_not_spend=True,
        old_unknowns_preserved=True))
    ledger=DispatchBudget(private/'ledger.db',{'native_compact':dict(arm='native_compact',limits=LIMITS,
        binding=dict(registration_sha256=sha256((private/'registration.json').read_bytes()).hexdigest()))},LIMITS)
    ticket=ledger.reserve('native_compact','one-compaction',LIMITS)
    rpc=None;worker=None;session=None;gate=None;errors=[];phase=None;settled=False
    def exchange(raw):
        ledger.remaining(ticket['ticket'])
        return provider(raw)
    def pump():
        try:
            frame=receive(worker.stdout)
            if frame.get('kind')!='request' or frame.get('ordinal')!=1:raise ValueError('compaction_worker_order')
            reply,error=dispatch(gate,frame['request'],1);send(worker.stdin,reply)
            if error:errors.append(error)
        except Exception as error:errors.append(dict(type=type(error).__name__,code=str(error)))
    try:
        with (private/'worker-stderr.txt').open('x',encoding='utf-8') as stderr:
            worker=subprocess.Popen(worker_args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if receive(worker.stdout)!={'kind':'ready'}:raise ValueError('compaction_worker_unready')
        gate=ProviderGate(model='gpt-6.1-sol',max_calls=1,seconds=180,directory=private/'requests',exchange=exchange,
            require_compaction_v2=True)
        thread=threading.Thread(target=pump,daemon=True);thread.start()
        rpc=BridgeRPC(args,private/'native-stderr.txt')
        rpc.call('initialize',dict(clientInfo=dict(name='wsc_native_v2_admission',version='1'),capabilities=dict(experimentalApi=True)),timeout=15)
        rpc.send(dict(method='initialized'))
        opened=rpc.call('thread/start',dict(cwd='/work/actor',model='gpt-6.1-sol',allowProviderModelFallback=False,
            approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=['/work/actor'],ephemeral=False,dynamicTools=[]),timeout=20)
        if opened['model']!='gpt-6.1-sol' or opened['reasoningEffort']!='max':raise ValueError('compaction_model_changed')
        rpc.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=prefix),timeout=10)
        native_path=actor/str(PurePosixPath(opened['thread']['path']).relative_to('/work'))
        deadline=time.monotonic()+3
        while not native_path.exists() and time.monotonic()<deadline:time.sleep(.05)
        session=MappedContextSession(dict(workspace='/work/actor',model='gpt-6.1-sol',effort='max'),private/'session',
            server=rpc,opened=opened,actor_root=actor,cleanup=lambda server:server.close())
        before=native_path.read_bytes();(private/'before.jsonl').write_bytes(before)
        ledger.bind_input(ticket['ticket'],dict(history_sha256=sha256(before).hexdigest(),operation='native_compact',profile=PROFILE))
        phase=session.execute_stage('Explicit native compaction admission',private/'compaction',
            ledger.remaining(ticket['ticket']),lambda p:None,compact=True)
        after=(private/'compaction/rollout.jsonl').read_bytes()
        events=[json.loads(line) for line in (private/'compaction/events.jsonl').read_text().splitlines() if line]
        proof=compression_evidence(before,after,phase,events)
        effective=state(parse_rollout(after).rows)
        opaque=[i for i in effective if i.get('type')=='compaction' and type(i.get('encrypted_content')) is str]
        qualified=proof['confirmed'] and bool(opaque) and not errors
        outcome=dict(qualified=qualified,model_requests_attempted=len(provider.trace),source_history_reused=True,
            usage_complete=phase['usage_complete'],receipts=phase['receipts'],failure=phase.get('failure'),
            compression_evidence=proof,opaque_item_count=len(opaque),summary_content_inspected=False,
            provider_trace=provider.trace,gateway_errors=errors,profile=PROFILE,
            native_default_websocket_performance_claimed=False,task_quality_tested=False,BC_comparison_completed=False)
        outcome['settlement']=ledger.settle(ticket['ticket'],phase);settled=True
        ledger.finish('native_compact',dict(success=qualified,outcome=outcome))
        save(out/'results.json',outcome)
        print(json.dumps({k:outcome[k] for k in ['qualified','model_requests_attempted','usage_complete','opaque_item_count','failure']}))
    except BaseException as error:
        save(out/'error.json',dict(type=type(error).__name__,error=str(error)));raise
    finally:
        if not settled:
            try:ledger.settle(ticket['ticket'],phase or dict(usage_complete=False,receipts=dict(response_receipts=[]),failure='admission_incomplete'))
            except Exception as error:save(out/'budget-error.json',dict(type=type(error).__name__,code=str(error)))
        ledger.close()
        save(private/'provider-trace.json',provider.trace)
        if gate:save(private/'gate-trace.json',gate.trace)
        save(private/'owner-errors.json',errors)
        if session and not session.closed:
            try:session.close()
            except Exception:pass
        if rpc and rpc.proc.stdin and not rpc.proc.stdin.closed:rpc.proc.stdin.close()
        if worker and worker.stdin and not worker.stdin.closed:worker.stdin.close()
        cleanup=subprocess.run(['wsl','--terminate','docker-desktop'],capture_output=True,timeout=15)
        save(out/'cleanup.json',dict(exit_code=cleanup.returncode))
        if worker:worker.wait(timeout=5);worker.stdout.close()
        if rpc and not session:rpc.proc.wait(timeout=5);rpc.proc.stdout.close();rpc.stderr.close()
        save(private/'closed-ledger.json',inspect_ledger(private/'ledger.db'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--owned-wsl-distribution',action='store_true',required=True);main(p.parse_args().out.resolve())
