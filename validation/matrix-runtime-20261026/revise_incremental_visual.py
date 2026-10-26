"""One incremental revision of the retained three records with source-bound clipping evidence."""
from dataclasses import fields
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, digest, usage
from native_scoped_selection_state import load, as_event
from native_application_session import NativeApplicationSession
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope
from native_incremental_candidate import prepare, admit_rendered, frontier
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_typed_content import dependencies
from native_rollout_snapshot import capture_rollout
from wsc import WSC, Store, events
from wsc.contracts import Event, encode
from wsc.publication import check_evidence
from wsc.source_reference_view import MODE
import native_cold_access

COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-dev-C-sharedtime-20261026-v1')
SELECT = Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1')
INPUT = SELECT / 'incremental-review-input'
OUT = Path('D:/agent-task-runs/wsc-a3-incremental-visual-20261026-v1')


def execute():
    OUT.mkdir(exist_ok=False)
    history = read(SELECT / 'result.json')
    assert history['cleanup']['empty_confirmed'] and not history['ledger']['inflight']
    envelope = qualification_envelope(history['ledger'], [],
        sum(arm['seconds'] for arm in history['ledger']['arms'].values()))
    common_reg = read(COMMON / 'registration.json')
    limits = common_reg['conditions']['budgets']['boundary_phase']
    workspace = Path(read(SELECT/'registration.json')['session']['workspace'])
    from native_visual_source_observation import from_probe
    actual = from_probe(workspace/'gui', SELECT/'S2-clipping-check/registration.json', SELECT/'S2-clipping-check/result.json')
    assert actual == read(SELECT/'current-visual-observation.json')
    state_path = PRIOR / 'scoped-selection-state.json'
    state_ref = dict(path=str(state_path), sha256=file_hash(state_path))
    load(state_ref, receiving_workspace=workspace)
    source = sqlite3.connect('file:'+str(INPUT/'state.db')+'?mode=ro',uri=True)
    target = sqlite3.connect(OUT/'state.db')
    source.backup(target); source.close(); target.close()
    core = WSC(Store(OUT/'state.db', session_id='a3/scoped-selection-v1/C', workspace=str(workspace)), access=lambda *args: True)
    previous = read(INPUT/'previous.json')
    before = core.capture()
    assert len(before.understandings)==3 and before.cut==previous['cut']+1
    assert before.events[-1]['payload']==actual
    material, offered = frontier(core,before,previous,OUT/'cold-public')
    assert len(offered['understandings'])==3 and len(offered['previous_selection']['clues'])==2
    assert material['events'][-1]['text_in_frontier']
    save(OUT/'input-binding.json',dict(prior_records=3,prior_clues=2,previous_cut=previous['cut'],
        current_cut=before.cut,source_digest=before.source_digest,previous_sha256=file_hash(INPUT/'previous.json'),
        source_observation=actual,prepared_database_sha256=file_hash(INPUT/'state.db'),
        scope='One added factual observation; previous model records and source prefix retained, not hand rewritten'))
    payload = read(COMMON/'staged/payload-C.json')
    runtime = workspace/'.wsc-runtime/browsers'
    assert runtime.is_dir(), 'registered_runtime_missing'
    reg = {**payload['registration'],'workspace':str(workspace),'sandbox':'read-only',
        'browser_cache':str(runtime)}
    for key in ('parent_thread_id','parent_paths','before_turn_id','browser_probe','browser_probe_sha256'):
        reg.pop(key,None)
    session = NativeApplicationSession(reg,OUT/'selector')
    reg['initial_manifest'] = session.source_manifest()
    pins = {str(path):file_hash(path) for path in [state_path,SELECT/'result.json',SELECT/'registration.json',INPUT/'state.db',INPUT/'previous.json',SELECT/'current-visual-observation.json',SELECT/'S2-clipping-check/result.json',SELECT/'S2-clipping-check/registration.json',Path(__file__).resolve()]}
    pins.update({str(path):file_hash(path) for folder in ('src','experiments') for path in (ROOT/folder).rglob('*.py')})
    save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),session=reg,
        envelope=envelope, limits=limits, pins=pins, scoped_state=state_ref, previous_registration=str(SELECT/'registration.json'),
        schema_mode='manifest_scope_and_delivery_stage_v1', automatic_retries=0, generation_attempts=1,
        whole_campaign_usage_complete=False, scope='Single incremental selection and compile/export only; no development or formal B/C'))
    budget = StudyBudget({'C/incremental-visual':limits},envelope['remaining_limits'])
    phases = []
    started = False
    outcome = dict(state='preflight',whole_campaign_usage_complete=False)
    try:
        session.open()
        def selected(offered):
            native_cold_access.material(session,offered,OUT/'material-access',dependencies(core))
            def native_generate(request,schema):
                nonlocal started
                ticket,granted=budget.reserve('C/incremental-visual',limits)
                save(OUT/'grant.json',dict(ticket=ticket,limits=granted,ledger=budget.snapshot()))
                def record(phase):
                    phases.append(phase);save(OUT/'phase-journal.json',phase)
                    result=budget.settle(ticket,phase)
                    save(OUT/'settlement.json',dict(result=result,ledger=budget.snapshot()))
                print(dict(state='generating_once',limits=granted),flush=True)
                started=True
                phase=session.execute_stage(encode(request),OUT/'selection-phase',granted,record,output_schema=schema)
                return phase,OUT/'selection-phase/rollout.jsonl'
            return generate(offered,native_generate,OUT/'generation',short_span_handles=True,scoped_manifest_bindings=True)
        view=prepare(core,core.capture(),previous,OUT/'cold-public',selected,source_projection=MODE)
        operation=core.stage(view['view'],directory=OUT/'exports',archive_directory=OUT/'cold-objects',adapter=IndexedCheckpointAdapter())
        package=admit_rendered(core.package(operation));check_evidence(core,package)
        native_cold_access.package(session,package,OUT/'export-access',dependencies(core))
        save(OUT/'package.json',package);save(OUT/'continuation.json',view['continuation']);core.discard(operation)
        outcome.update(state='exported',rendered_bytes=len(encode(package['items']).encode()))
    except Exception as error:
        outcome.update(state='failed',error=type(error).__name__+':'+str(error))
        if started and not phases:budget.mark_unknown('C/incremental-visual')
    finally:
        outcome['cleanup']=session.close()
        if session.opened:
            snap=capture_rollout(session.opened['thread']['path'],archive=OUT/'closed-native.jsonl')
            expected={row['response_id']:row['usage'] for phase in phases for row in phase.get('receipts',{}).get('response_receipts',[])}
            actual={row['payload']['response_id']:row['payload']['usage'] for row in snap.rows if row['type']=='token_usage_record'}
            late=[row for row in snap.rows if row['type']=='token_usage_record' and row['payload']['response_id'] not in expected]
            if any(actual.get(key)!=value for key,value in expected.items()) or late or not snap.metadata['parse_complete']:
                budget.mark_unknown('C/incremental-visual',usage(late,session.opened['thread']['id'])['response_receipts'] if late else ())
                outcome['state']='accounting_unknown'
        outcome['source_unchanged']=session.source_manifest()==reg['initial_manifest']
        outcome['pins_unchanged']=all(file_hash(path)==value for path,value in pins.items())
        outcome['ledger']=budget.snapshot();outcome['inference_started']=started
        outcome['selection_transport_passed']=(outcome['state']=='exported' and outcome['source_unchanged']
            and outcome['pins_unchanged'] and outcome['cleanup']['empty_confirmed'] and not outcome['ledger']['study']['uncertain'])
        outcome['semantic_review']='pending';outcome['development_started']=False
        save(OUT/'result.json',outcome)
    print({key:outcome.get(key) for key in ('state','error','rendered_bytes','selection_transport_passed')},flush=True)


if __name__=='__main__':execute()
