"""One bounded incremental selection after source-equivalent replay and calibration."""
from pathlib import Path
from datetime import datetime,timezone
import sys,time,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,usage
from native_application_session import NativeApplicationSession
from native_application_budget import StudyBudget
from native_incremental_candidate import prepare,admit_rendered
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_typed_content import dependencies
from native_rollout_snapshot import capture_rollout
from native_paired_evaluation import load_facts,as_event
from wsc import WSC,Store
from wsc.contracts import Event,encode
from wsc.publication import check_evidence
from wsc.source_reference_view import MODE
import native_cold_access
OUT=Path('D:/agent-task-runs/wsc-a3-calibrated-selection-20261026-v1')
BASE=Path('D:/agent-task-runs/wsc-paired-writable-admission-20261026-v1')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
reg=read(OUT/'session-registration.json');previous=read(OUT/'previous.json')
assert read(OUT/'replay-proof.json')['selected_body_identical']
assert not (OUT/'registration.json').exists()
core=WSC(Store(OUT/'state.db',session_id='a3/calibrated-selection-v1/C',workspace=reg['workspace']),access=lambda *a:True)
before=core.capture();assert before.cut==201 and len(before.understandings)==4
facts=load_facts(reg);event=read(BASE/'pending-S2-observation-event.json')
assert event['payload']['original_gui_source_sha256']==facts['source_binding']['sha256']
for ref in event['payload']['receipts']:assert file_hash(ref['path'])==ref['sha256']
core.ingest([as_event(facts),Event(**event)])
after=core.capture()
assert after.events[:201]==before.events and after.understandings==before.understandings
save(OUT/'new-source-binding.json',dict(previous_cut=201,current_cut=after.cut,
 old_events_unchanged=True,old_understandings_unchanged=True,new_sources=[row['id'] for row in after.events[201:]],
 core_workspace=core.store.workspace,source_manifest_matches_reviewed_S2=True))
envelope=read(BASE/'next-admission-envelope.json')
caps=dict(envelope['remaining_limits']);elapsed=time.time()-(BASE/'next-admission-envelope.json').stat().st_mtime
assert elapsed>=0
caps['max_seconds']-=math.ceil(elapsed);assert caps['max_seconds']>180
limits=read(COMMON/'registration.json')['conditions']['budgets']['boundary_phase']
budget=StudyBudget({'C/calibrated-selection':limits},caps)
session=NativeApplicationSession(reg,OUT/'selector')
assert session.source_manifest()==reg['initial_manifest']
pins={str(p):file_hash(p) for p in [OUT/'session-registration.json',OUT/'replay-proof.json',OUT/'previous.json',
 BASE/'component-calibration-observation.json',BASE/'pending-S2-observation-event.json',BASE/'next-admission-envelope.json',Path(__file__).resolve()]}
pins.update({str(p):file_hash(p) for folder in ('src','experiments') for p in (ROOT/folder).rglob('*.py')})
save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),session=reg,pins=pins,
 limits=limits,remaining_study_limits=caps,prior_envelope=envelope,model_selection_attempts=1,automatic_retries=0,
 previous_source=str(BASE/'next-admission-envelope.json'),whole_campaign_usage_complete=False,
 scope='One incremental selection with reused records; no development, compaction control or formal BC'))
phases=[];started=False;outcome=dict(state='preflight',development_started=False,whole_campaign_usage_complete=False)
try:
 session.open()
 def select(offered):
  native_cold_access.material(session,offered,OUT/'material-access',dependencies(core))
  def execute(request,schema):
   global started
   ticket,granted=budget.reserve('C/calibrated-selection',limits)
   save(OUT/'grant.json',dict(ticket=ticket,limits=granted,ledger=budget.snapshot()))
   def record(phase):
    phases.append(phase);save(OUT/'phase-journal.json',phase)
    settled=budget.settle(ticket,phase);save(OUT/'settlement.json',dict(settled=settled,ledger=budget.snapshot()))
   print(dict(state='generating_once',limits=granted),flush=True)
   started=True
   phase=session.execute_stage(encode(request),OUT/'selection-phase',granted,record,output_schema=schema)
   return phase,OUT/'selection-phase/rollout.jsonl'
  return generate(offered,execute,OUT/'generation',short_span_handles=True,scoped_manifest_bindings=True)
 view=prepare(core,core.capture(),previous,OUT/'cold-public',select,source_projection=MODE)
 operation=core.stage(view['view'],directory=OUT/'exports',archive_directory=OUT/'cold-objects',adapter=IndexedCheckpointAdapter())
 package=admit_rendered(core.package(operation));check_evidence(core,package)
 native_cold_access.package(session,package,OUT/'export-access',dependencies(core))
 save(OUT/'package.json',package);save(OUT/'continuation.json',view['continuation']);core.discard(operation)
 outcome.update(state='exported',rendered_bytes=len(encode(package['items']).encode()))
except Exception as error:
 outcome.update(state='failed',error=type(error).__name__+':'+str(error))
 if started and not phases:budget.mark_unknown('C/calibrated-selection')
finally:
 outcome['cleanup']=session.close()
 if session.opened:
  snap=capture_rollout(session.opened['thread']['path'],archive=OUT/'closed-native.jsonl')
  expected={r['response_id']:r['usage'] for phase in phases for r in phase.get('receipts',{}).get('response_receipts',[])}
  actual={r['payload']['response_id']:r['payload']['usage'] for r in snap.rows if r['type']=='token_usage_record'}
  late=[r for r in snap.rows if r['type']=='token_usage_record' and r['payload']['response_id'] not in expected]
  if any(actual.get(k)!=v for k,v in expected.items()) or late or not snap.metadata['parse_complete']:
   budget.mark_unknown('C/calibrated-selection',usage(late,session.opened['thread']['id'])['response_receipts'] if late else ())
   outcome['state']='accounting_unknown'
 outcome.update(source_unchanged=session.source_manifest()==reg['initial_manifest'],
  pins_unchanged=all(file_hash(p)==h for p,h in pins.items()),ledger=budget.snapshot(),inference_started=started)
 outcome['transport_passed']=(outcome['state']=='exported' and outcome['source_unchanged'] and outcome['pins_unchanged']
  and bool(outcome['cleanup'] and outcome['cleanup']['empty_confirmed']) and not outcome['ledger']['study']['uncertain'])
 save(OUT/'result.json',outcome)
print({k:outcome.get(k) for k in ('state','error','rendered_bytes','transport_passed')},flush=True)
