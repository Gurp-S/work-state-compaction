"""One unchanged native B compaction seed, shared across actor repetitions."""
from pathlib import Path
from datetime import datetime, timezone
import math
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,digest,usage
from native_study_fork_session import NativeForkSession
from native_application_capability import admit
from native_application_budget import StudyBudget
from native_rollout_snapshot import capture_rollout
from native_campaign_envelope import qualification_envelope
import native_cold_access

COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
OUT=COHORT/'B-seed-v2'
OUT.mkdir(exist_ok=False)
registration=read(COHORT/'registration.json')
reg=registration['sessions']['B']
assert 'native_c_auto_compaction' not in reg and 'before_turn_id' not in reg
source=COHORT/'B-seed/next-admission-envelope.json'
envelope=read(source)
envelope['remaining_limits']['max_seconds']-=math.ceil(max(0,time.time()-source.stat().st_mtime))
limits=read(Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/registration.json'))['conditions']['budgets']['boundary_phase']
budget=StudyBudget({'B-fixed-seed':limits},envelope['remaining_limits'])
bundle=read(COHORT/'shared-raw-observations.json')
assert file_hash(COHORT/'shared-raw-observations.json')==registration['common_raw_observations_sha256']
assert digest([row['payload'] for row in bundle['sources']])==registration['raw_observation_payloads_sha256']
save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),session=reg,limits=limits,
    envelope=envelope,parent_envelope_sha256=file_hash(source),cohort_sha256=file_hash(COHORT/'registration.json'),
    generation='native default thread/compact/start, idle thread; no custom prompt',automatic_retries=0,
    source_raw_observations_sha256=file_hash(COHORT/'shared-raw-observations.json'),whole_campaign_usage_complete=False))
(OUT/'controller.py').write_bytes(Path(__file__).read_bytes())
session=NativeForkSession(reg,OUT/'session')
phases=[]
result={}
begin=time.monotonic()
ticket=None
try:
    session.open()
    capsule=read(Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/capsule.json'))
    root=capsule['root_history']
    assert file_hash(Path(root['archive']))==root['sha256'], 'B_seed_registered_root_changed'
    assert any(parent['thread_id']==root['thread_id'] and parent['prefix_sha256']==root['sha256']
        for parent in session.fork_binding['parents']), 'B_seed_history_not_same_S2'
    admit(session,OUT/'browser-capability')
    runtime=dict(kind='native_execution_transition',current_workspace=reg['workspace'],inherited_context_source='shared_S2',
        business_manifest_sha256=digest(reg['initial_manifest']),allocated_local_ports=[29510,29511,29512])
    import json
    session.inject([dict(type='message',role='developer',content=[dict(type='input_text',text=json.dumps(value,ensure_ascii=False))])
        for value in (bundle,runtime)])
    package=read(COHORT/'C-package.json')
    assert all(read(Path(package['evidence'][row['source_id']]['file_path']))==row['payload'] for row in bundle['sources'])
    native_cold_access._check(session,[(package['evidence'][row['source_id']]['file_path'],package['evidence'][row['source_id']]['sha256'])
        for row in bundle['sources']],OUT/'shared-source-cold-access')
    ticket,grant=budget.reserve('B-fixed-seed',limits)
    save(OUT/'grant.json',dict(ticket=ticket,limits=grant))
    def record(phase):
        phases.append(phase);save(OUT/'phase-journal.json',phase)
        save(OUT/'settlement.json',budget.settle(ticket,phase))
    print('One native B seed compaction running',flush=True)
    phase=session.execute_stage('native_compaction',OUT/'compaction',grant,record,compact=True)
    result.update(completed=phase['completed'],usage_complete=phase['usage_complete'],failure=phase['failure'])
except Exception as error:
    result['error']=type(error).__name__+':'+str(error)
    if ticket and not phases:budget.mark_unknown('B-fixed-seed')
finally:
    result['cleanup']=session.close()
    if session.opened:
        snap=capture_rollout(session.opened['thread']['path'],archive=OUT/'closed-native.jsonl')
        expected={r['response_id']:r['usage'] for p in phases for r in p['receipts']['response_receipts']}
        actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
        if actual!=expected or not snap.metadata['parse_complete']:
            late=[r for r in snap.rows if r['type']=='token_usage_record' and r['payload']['response_id'] not in expected]
            budget.mark_unknown('B-fixed-seed',usage(late,session.opened['thread']['id'])['response_receipts'] if late else ())
            result['accounting_mismatch']=True
        result['thread_id']=session.opened['thread']['id']
        result['rollout_path']=session.opened['thread']['path']
        result['native_source_sha256']=snap.metadata['sha256']
    result.update(ledger=budget.snapshot(),seconds=time.monotonic()-begin,whole_campaign_usage_complete=False,
        source_unchanged=session.source_manifest()==reg['initial_manifest'],
        seed_scope='One fixed native compression, not three independent compression-generation repetitions')
    save(OUT/'result.json',result)
    if not result['ledger']['inflight']:
        next_envelope=qualification_envelope(result['ledger'],[],result['seconds'])
        next_envelope.update(old_unknowns_preserved=True,whole_campaign_usage_complete=False,
            parent_result=dict(path=str(OUT/'result.json'),sha256=file_hash(OUT/'result.json')))
        save(OUT/'next-admission-envelope.json',next_envelope)
print({key:result.get(key) for key in ('completed','usage_complete','error','failure','accounting_mismatch')},flush=True)
