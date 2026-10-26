"""Zero-inference paired input/import admission; shared runtime is read-only only."""
from pathlib import Path
from datetime import datetime,timezone
import os,sys,shutil,subprocess,json,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,manifest,digest
from native_fixture_transport import attach as transport_attach,public_binding
from native_evaluation_context import capture,from_bound_probe
from native_evaluation_host import MODE
from native_paired_evaluation import configure,load_facts,grade_path,as_event
from native_application_session import NativeApplicationSession
from native_campaign_envelope import qualification_envelope
from native_rollout_snapshot import capture_rollout
from wsc import WSC,Store
from wsc.contracts import encode
import native_cold_access

OUT=Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
CAL=Path('D:/agent-task-runs/wsc-evaluation-context-20261026-v1')
PRIOR=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
CURRENT=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace')
resume = len(sys.argv)>1 and sys.argv[1]=='resume-after-port-error'
if resume:
    assert read(OUT/'S2-execution.json')['exit_code'] != 0
    assert not (OUT/'paired-S2-facts.json').exists() and not (OUT/'registration.json').exists()
else:
    OUT.mkdir(exist_ok=False)
attempt = 'S2-after-port-error' if resume else 'S2'

prior=read(PRIOR/'result.json')
assert prior['cleanup']['empty_confirmed'] and not prior['ledger']['inflight']
ledger_hash=file_hash(PRIOR/'result.json')
envelope=qualification_envelope(prior['ledger'],[],read(PRIOR/'phase-journal.json')['seconds'])
assert prior['ledger']['study']['uncertain'] and envelope['historical_uncertainty']
source_reg=read(COMMON/'registration.json');payload=read(COMMON/'staged/payload-C.json')
frozen=read(source_reg['tasks']['a3']['binding'])['workspace']
source=COMMON/'staged/frozen-workspace';source_manifest=manifest(source)
assert source_manifest==read(COMMON/'staged/capsule.json')['source_manifest']
conditions=dict(fixture_transport='http_attached_websocket_v1',evaluation_host=MODE)
probe=Path(__file__).parent/'check_s2_clipping.mjs'
regs={}
for arm in ('B','C'):
    work=OUT/arm/'workspace'
    if not resume:
        work.parent.mkdir()
        shutil.copytree(source,work)
    # No paid development permitted on these shared dependency junctions.
    if not resume: subprocess.run(['powershell.exe','-NoProfile','-Command',f"New-Item -ItemType Junction -Path '{work/'gui/node_modules'}' -Target '{CURRENT/'gui/node_modules'}' | Out-Null"],check=True,capture_output=True)
    reg={**payload['registration'],'workspace':str(work),'initial_manifest':source_manifest,'sandbox':'read-only',
        'browser_cache':str(work/'.wsc-runtime/browsers')}
    for key in ('parent_thread_id','parent_paths','before_turn_id','browser_probe','browser_probe_sha256'):
        reg.pop(key,None)
    reg=transport_attach(reg,frozen)
    Path(reg['browser_cache']).mkdir(exist_ok=True)
    regs[arm]=configure(reg,frozen,conditions)
# Fresh v2 receipt; old v1 context is retained, not retrospectively upgraded.
gui=Path(regs['B']['workspace'])/'gui';fixture=Path(regs['B']['fixture_root'])
context=capture(gui,fixture,probe,entry='production_panel',scenario='normal',viewport=dict(width=1440,height=1000))
save(OUT/(attempt+'-context-registration.json'),context)
env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(CURRENT/'.wsc-runtime/browsers')}
command=['E:/nodejs/node.exe',str(probe.resolve()),str(gui),str(fixture),str(OUT/(attempt+'-geometry'))]
process=subprocess.run(command,env=env,capture_output=True,encoding='utf-8',errors='strict',timeout=60)
save(OUT/(attempt+'-execution.json'),dict(command=command,exit_code=process.returncode,stdout=process.stdout,stderr=process.stderr))
assert process.returncode==0,process.stderr
observation=from_bound_probe(gui,fixture,probe,OUT/(attempt+'-context-registration.json'),OUT/(attempt+'-geometry')/'registration.json',OUT/(attempt+'-geometry')/'result.json')
assert not observation['clipping_observed'] and observation['real_wheel_changed_scroll']
save(OUT/'S2-observation.json',observation)
facts=read(CAL/'paired-S2-facts.json')
facts.update(kind='shared_S2_evaluation_facts_v2',execution_context=context,
    probe=dict(path=str(probe.resolve()),sha256=file_hash(probe)))
facts['visual'].update(host_binding=context['host'],execution_context_sha256=digest(context),
    receipt=dict(path=str(OUT/'S2-observation.json'),sha256=file_hash(OUT/'S2-observation.json')))
save(OUT/'paired-S2-facts.json',facts)
conditions['shared_S2_evaluation_facts']=dict(path=str(OUT/'paired-S2-facts.json'),sha256=file_hash(OUT/'paired-S2-facts.json'))
loaded={};routes={}
for arm in ('B','C'):
    # Reuse the verified original transport as configure input; no repeat materialization.
    original={**regs[arm],'fixture_root':str(Path(regs[arm]['workspace'])/'.wsc-runtime/fixture-transport-v1')}
    regs[arm]=configure(original,frozen,conditions)
    loaded[arm]=load_facts(regs[arm]);routes[arm]=str(grade_path(regs[arm]['workspace'],frozen,conditions,Path('unused')))
    assert routes[arm]==public_binding(regs[arm])['public_acceptance_harness']
assert encode(loaded['B'])==encode(loaded['C'])
assert encode(loaded['B']['execution_context'])==encode(loaded['C']['execution_context'])
assert regs['B']['fixture_root']!=regs['C']['fixture_root']
assert grade_path(regs['B']['workspace'],frozen,{},Path('old-default'))==Path('old-default')
assert configure({'old':'default'},frozen,{})=={'old':'default'}
# The C selected-material source receives the identical fact as B's native message.
core=WSC(Store(OUT/'C/wsc.db',session_id='paired-evaluation/C',workspace=regs['C']['workspace']),access=lambda *args:True)
core.ingest([as_event(loaded['C'])]);assert core.capture().events[0]['text']==encode(loaded['B'])
from native_incremental_candidate import frontier
_,offered=frontier(core,core.capture(),None,OUT/'C/cold-public')
assert offered['events'] and core.capture().events[0]['payload']==loaded['B']
save(OUT/'registration.json',dict(created_at=datetime.now(timezone.utc).isoformat(),conditions=conditions,
    sessions=regs,envelope=envelope,prior_result=dict(path=str(PRIOR/'result.json'),sha256=ledger_hash),
    inference_permitted=False,model_calls=0,scope='Read-only native import/cold access; shared runtime junctions, not writable development qualification'))
proofs={}
for arm in ('B','C'):
    session=NativeApplicationSession(regs[arm],OUT/arm/'native-receiver')
    proof={}
    try:
        session.open()
        item=dict(type='message',role='developer',content=[dict(type='input_text',text=encode(loaded[arm]))])
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[item]))
        snap=capture_rollout(session.opened['thread']['path'],archive=OUT/arm/'injected.jsonl')
        actual=[row['payload'] for row in snap.rows if row['type']=='response_item' and row['payload'].get('role')=='developer']
        assert any(row.get('content')==item['content'] for row in actual)
        assert not any(row['type']=='token_usage_record' for row in snap.rows)
        receipts=[facts['visual']['receipt'],facts['component_baseline']['receipt'],conditions['shared_S2_evaluation_facts']]
        native_cold_access._check(session,[(r['path'],r['sha256']) for r in receipts],OUT/arm/'native-cold-check')
        proof.update(facts_sha256=digest(loaded[arm]),facts_installed_exactly=True,cold_access_passed=True)
    finally:
        proof['cleanup']=session.close()
        if proof['cleanup'] is None:
            assert session.server is None and session.opened is None
            proof['cleanup']=dict(empty_confirmed=True,process_started=False)
        assert proof['cleanup']['empty_confirmed']
        if session.opened:
            closed=capture_rollout(session.opened['thread']['path'],archive=OUT/arm/'closed-native.jsonl')
            assert closed.metadata['parse_complete'] and not any(row['type']=='token_usage_record' for row in closed.rows)
        proof['business_source_unchanged']=session.source_manifest()==source_manifest
        assert proof['business_source_unchanged']
        save(OUT/arm/'result.json',proof)
    proofs[arm]=proof
# Refuse changed C source before any model call, and restore the diagnostic byte.
p=Path(regs['C']['workspace'])/'gui/src/components/A3NativePanel.tsx';original=p.read_bytes()
try:
    p.write_bytes(original+b'\n// changed')
    try:load_facts(regs['C'])
    except ValueError as error:rejection=str(error)
    else:raise AssertionError('changed receiver accepted')
finally:p.write_bytes(original)
assert file_hash(PRIOR/'result.json')==ledger_hash
save(OUT/'result.json',dict(model_calls=0,model_execution_permitted=False,native_receivers=2,
    identical_shared_facts=True,identical_execution_context=True,material_and_native_fact_identical=True,
    native_import_and_cold_access_passed=True,both_sources_unchanged=True,changed_source_rejected=rejection,
    prepared_and_grade_harness_paths_match=True,default_routes_unchanged=True,
    prior_unknown_preserved=True,prior_ledger_unchanged=True,original_ledger_resumed=False,
    facts_bytes=len(encode(facts).encode()),formal_BC_started=False,whole_goal_achieved=False,
    writable_runtime_isolation_qualified=False,
    scope='Real zero-inference paired native input admission only; no development, native compaction or performance result',
    next_step='Review expected information gain and cumulative budget for a bounded development comparison; no automatic 6M rerun'))
print(json.dumps(read(OUT/'result.json'),ensure_ascii=False))
