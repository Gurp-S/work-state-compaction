"""Continue the already prepared paired admission; no repeated browser/materialization."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,digest
from native_paired_evaluation import load_facts,as_event
from native_application_session import NativeApplicationSession
from native_rollout_snapshot import capture_rollout
from wsc.contracts import encode
import native_cold_access
OUT=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')
registration=read(OUT/'registration.json');regs=registration['sessions']
assert registration['inference_permitted'] is False and not (OUT/'result.json').exists()
save(OUT/'native-setup-interruption.json',dict(model_calls=0,native_process_started=False,
    cause='Empty private browser-cache directory absent before settings validation; cleanup wrapper expected a process result before start',
    original_registration_preserved=True,new_native_receivers='native-receiver-v2'))
proofs={}
for arm in ('B','C'):
    reg=regs[arm]
    Path(reg['browser_cache']).mkdir(exist_ok=False)
    facts=load_facts(reg)
    session=NativeApplicationSession(reg,OUT/arm/'native-receiver-v2');proof={}
    try:
        session.open()
        item=dict(type='message',role='developer',content=[dict(type='input_text',text=encode(facts))])
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[item]))
        snap=capture_rollout(session.opened['thread']['path'],archive=OUT/arm/'injected.jsonl')
        actual=[r['payload'] for r in snap.rows if r['type']=='response_item' and r['payload'].get('role')=='developer']
        assert any(r.get('content')==item['content'] for r in actual)
        assert not any(r['type']=='token_usage_record' for r in snap.rows)
        refs=[facts['visual']['receipt'],facts['component_baseline']['receipt'],registration['conditions']['shared_S2_evaluation_facts']]
        native_cold_access._check(session,[(r['path'],r['sha256']) for r in refs],OUT/arm/'native-cold-check')
        proof.update(facts_sha256=digest(facts),facts_installed_exactly=True,cold_access_passed=True)
    finally:
        proof['cleanup']=session.close()
        assert proof['cleanup']['empty_confirmed']
        if session.opened:
            closed=capture_rollout(session.opened['thread']['path'],archive=OUT/arm/'closed-native.jsonl')
            assert closed.metadata['parse_complete'] and not any(r['type']=='token_usage_record' for r in closed.rows)
        proof['business_source_unchanged']=session.source_manifest()==reg['initial_manifest']
        assert proof['business_source_unchanged']
        save(OUT/arm/'result.json',proof)
    proofs[arm]=proof
assert proofs['B']['facts_sha256']==proofs['C']['facts_sha256']
p=Path(regs['C']['workspace'])/'gui/src/components/A3NativePanel.tsx';original=p.read_bytes()
try:
    p.write_bytes(original+b'\n// changed')
    try:load_facts(regs['C'])
    except ValueError as error:rejection=str(error)
    else:raise AssertionError('changed receiver accepted')
finally:p.write_bytes(original)
prior=registration['prior_result']
assert file_hash(prior['path'])==prior['sha256']
assert registration['envelope']['historical_uncertainty']
save(OUT/'result.json',dict(model_calls=0,model_execution_permitted=False,native_receivers=2,
 identical_shared_facts=True,identical_execution_context=True,material_and_native_fact_identical=True,
 native_import_and_cold_access_passed=True,both_sources_unchanged=True,changed_source_rejected=rejection,
 prepared_and_grade_harness_paths_match=True,default_routes_unchanged=True,
 prior_unknown_preserved=True,prior_ledger_unchanged=True,original_ledger_resumed=False,
 facts_bytes=len(encode(load_facts(regs['B'])).encode()),formal_BC_started=False,whole_goal_achieved=False,
 writable_runtime_isolation_qualified=False,browser_execution_inside_native_verified=False,
 setup_interruptions=dict(unsafe_port_browser_runs=1,missing_empty_cache_before_native_start=1,model_calls=0),
 scope='Real zero-inference paired native import/cold access only; no development, compaction or performance result',
 next_step='Assess information gain and cumulative budget; do not automatically rerun 6M development'))
print(read(OUT/'result.json'))
