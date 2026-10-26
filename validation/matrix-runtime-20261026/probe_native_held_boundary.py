"""One registered dynamic-tool waiting-point capability check; no application task."""
from pathlib import Path
from datetime import datetime,timezone
import json,queue,sys,time,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,usage
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
from native_rollout_snapshot import capture_rollout
from native_turn_accounting import account_turn
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope

OUT=Path('D:/agent-task-runs')/(sys.argv[1] if len(sys.argv)>1 else 'native-boundary-capability-20261026-v1')
PARENT=Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
OUT.mkdir(exist_ok=False);WORK=OUT/'workspace';WORK.mkdir()
reg=read(PARENT/'registration.json')['session']
reg={k:reg[k] for k in ('executable','executable_sha256','model','effort','host_feature_overrides') if k in reg}
reg.update(workspace=str(WORK),sandbox='read-only')
assert file_hash(reg['executable'])==reg['executable_sha256']
envelope=read(PARENT/'next-admission-envelope.json')
caps=dict(envelope['remaining_limits'])
caps['max_seconds']-=math.ceil(time.time()-(PARENT/'next-admission-envelope.json').stat().st_mtime)
limits=dict(max_total_tokens=120000,max_responses=4,max_seconds=120)
assert caps['max_seconds']>120
budget=StudyBudget({'protocol/held-tool':limits},caps)
request='调用 checkpoint_ready 一次，参数为 {}。收到工具结果后，仅返回 {"done":true}。'
tool=dict(type='function',name='checkpoint_ready',description='Host-owned checkpoint boundary. No task file changes.',inputSchema=dict(type='object',properties={},required=[],additionalProperties=False))
save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),session=reg,limits=limits,
 remaining_study_limits=caps,parent_envelope=envelope,request=request,dynamic_tool=tool,
 automatic_retries=0,model_attempts=1,application_development=False,formal_BC=False,
 native_B_changed=False,scope='Dynamic-tool waiting and accounting capability only; no continuation/benefit proof'))
server=None;opened=None;turn_id=None;terminal=False;callback_seen=False;started=False;outcome={};before=b''
log=(OUT/'events.jsonl').open('x',encoding='utf-8');begin=time.monotonic()
ticket=None;receipts_at_gate=[]
def record(event):
 log.write(json.dumps(event,ensure_ascii=False)+'\n');log.flush()
def snapshot(name=None):
 return capture_rollout(opened['thread']['path'],archive=OUT/name if name else None)
try:
 server=OwnedNativeRPC(reg['executable'],cwd=WORK,stderr_path=OUT/'stderr.txt',settings=settings(reg))
 save(OUT/'initialized.json',server.call('initialize',dict(clientInfo=dict(name='boundary_capability',version='1'),capabilities=dict(experimentalApi=True))))
 server.send(dict(method='initialized'))
 opened=server.call('thread/start',dict(cwd=str(WORK),model=reg['model'],allowProviderModelFallback=False,
  approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=[str(WORK)],ephemeral=False,dynamicTools=[tool]),timeout=30)
 save(OUT/'thread-start.json',opened)
 assert opened['model']==reg['model'] and opened['reasoningEffort']==reg['effort']
 server.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=[dict(type='message',role='developer',content=[dict(type='input_text',text=json.dumps(dict(kind='execution_binding',current_workspace=str(WORK),execution_mode='read_only')))])]))
 path=Path(opened['thread']['path'])
 bootstrap_deadline=time.monotonic()+3
 while not path.exists() and time.monotonic()<bootstrap_deadline:time.sleep(.05)
 before=path.read_bytes()
 bootstrap=capture_rollout(path)
 assert bootstrap.metadata['parse_complete'] and not any(r['type']=='token_usage_record' for r in bootstrap.rows)
 ticket,grant=budget.reserve('protocol/held-tool',limits)
 save(OUT/'grant.json',dict(ticket=ticket,limits=grant,ledger=budget.snapshot()))
 started=True
 turn=server.call('turn/start',dict(threadId=opened['thread']['id'],model=reg['model'],effort=reg['effort'],input=[dict(type='text',text=request)]),timeout=20)
 turn_id=turn['turn']['id'];save(OUT/'turn-start.json',turn)
 print(dict(state='one_protocol_turn_running',limits=grant),flush=True)
 deadline=time.monotonic()+grant['max_seconds']
 while time.monotonic()<deadline:
  try:event=server.event(timeout=.25)
  except queue.Empty:continue
  record(event)
  method=event.get('method');params=event.get('params',{})
  if 'id' in event and method:
   assert method=='item/tool/call' and not callback_seen,'unexpected_server_callback'
   assert params['tool']=='checkpoint_ready' and params['arguments']=={} and params['turnId']==turn_id
   callback_seen=True;save(OUT/'held-callback.json',event)
   # Drain stream completion/usage while the tool response is deliberately withheld.
   gate_deadline=time.monotonic()+2
   while time.monotonic()<gate_deadline:
    try:pending=server.event(timeout=.1)
    except queue.Empty:continue
    record(pending)
    assert not ('id' in pending and pending.get('method')),'multiple_callbacks_while_held'
   gate=snapshot('held-native.jsonl')
   receipts_at_gate=[r for r in gate.rows if r['type']=='token_usage_record']
   save(OUT/'held-point.json',dict(receipt_count=len(receipts_at_gate),snapshot=gate.metadata,
    callback_response_withheld=True,provider_settlement_evidenced=bool(receipts_at_gate)))
   save(OUT/'held-thread-read.json',server.call('thread/read',dict(threadId=opened['thread']['id'],includeTurns=True)))
   # Only exercise active mutation if inference settlement has actually been observed.
   if receipts_at_gate:
    try:
     response=server.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=[dict(type='message',role='developer',content=[dict(type='input_text',text='{"boundary_probe_marker":"held"}')])]),timeout=8)
     outcome['held_injection']=dict(accepted=True,response=response)
    except Exception as error:outcome['held_injection']=dict(accepted=False,error=str(error))
    try:
     response=server.call('thread/compact/start',dict(threadId=opened['thread']['id']),timeout=8)
     outcome['held_compaction']=dict(accepted=True,response=response)
    except Exception as error:outcome['held_compaction']=dict(accepted=False,error=str(error))
   else:
    outcome['held_injection']=dict(attempted=False,reason='provider_settlement_not_observed')
    outcome['held_compaction']=dict(attempted=False,reason='provider_settlement_not_observed')
   save(OUT/'mutation-capability.json',dict(held_injection=outcome['held_injection'],held_compaction=outcome['held_compaction']))
   server.send(dict(id=event['id'],result=dict(success=True,contentItems=[dict(type='inputText',text='{"checkpoint":true}')])))
   outcome['tool_response_sent']=True
  if method=='turn/completed' and params['turn']['id']==turn_id:
   terminal=True;outcome['native_turn_status']=params['turn']['status'];break
  if method=='thread/tokenUsage/updated':
   current=usage(snapshot().rows,opened['thread']['id'])
   if current['response_count']>=grant['max_responses'] or current['all_usage']['total_tokens']>=grant['max_total_tokens']:
    outcome['failure']='registered_protocol_cap';break
except Exception as error:outcome['error']=type(error).__name__+':'+str(error)
finally:
 if server and turn_id and not terminal:
  try:
   server.call('turn/interrupt',dict(threadId=opened['thread']['id'],turnId=turn_id),timeout=8)
   end=time.monotonic()+4
   while time.monotonic()<end:
    try:event=server.event(timeout=.2)
    except queue.Empty:continue
    record(event)
    if event.get('method')=='turn/completed' and event.get('params',{}).get('turn',{}).get('id')==turn_id:
     terminal=True;break
  except Exception as error:outcome['interrupt_error']=str(error)
 outcome['cleanup']=server.close() if server else dict(empty_confirmed=True,process_started=False)
 log.close()
 if opened:
  closed=snapshot('closed-native.jsonl')
  ledger=usage(closed.rows,opened['thread']['id'])
  proof=account_turn(before,Path(opened['thread']['path']).read_bytes(),thread_id=opened['thread']['id'],turn_id=turn_id) if turn_id else None
  complete=bool(proof and proof['complete'] and terminal and not outcome.get('error') and outcome.get('native_turn_status')=='completed')
  phase=dict(seconds=time.monotonic()-begin,receipts=ledger,usage_complete=complete,completed=outcome.get('native_turn_status')=='completed',turn_accounting=proof)
  save(OUT/'phase-journal.json',phase)
  if ticket:budget.settle(ticket,phase)
 else:
  if started:budget.mark_unknown('protocol/held-tool')
 outcome.update(callback_observed=callback_seen,receipts_at_held_point=len(receipts_at_gate),terminal_observed=terminal,
  ledger=budget.snapshot(),application_development=False,whole_campaign_usage_complete=False,
  evidence_scope='One native dynamic-tool waiting point; API acceptance is not safe WSC publication proof')
 save(OUT/'result.json',outcome)
print({k:outcome.get(k) for k in ('callback_observed','receipts_at_held_point','held_injection','held_compaction','native_turn_status','error')},flush=True)
