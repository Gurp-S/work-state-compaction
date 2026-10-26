"""Zero-model calibration of opt-in host and before-execution context binding."""
import os,sys,subprocess,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,file_hash,manifest
from native_evaluation_host import materialize,verify
from native_evaluation_context import capture,from_bound_probe
from native_visual_source_observation import from_probe
OLD=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
WORK=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace')
COMMON=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT=Path('D:/agent-task-runs/wsc-evaluation-context-20261026-v1')
OUT.mkdir(exist_ok=False)
source_reg=read(COMMON/'registration.json')
frozen=read(source_reg['tasks']['a3']['binding'])['workspace']
upstream=WORK/'.wsc-runtime/fixture-transport-v1'
host=OUT/'production-panel-host'
original=manifest(upstream)
materialize(upstream,frozen,host)
probe=Path(__file__).parent/'check_s2_clipping.mjs'
current_source=manifest(WORK/'gui/src')
env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(WORK/'.wsc-runtime/browsers')}
values={}
for name,gui in [('S2',OLD/'component-source-ab/baseline/gui'),('C_S3',WORK/'gui')]:
    context=capture(gui,host,probe,entry='production_panel',scenario='normal',viewport=dict(width=1440,height=1000))
    reference=OUT/(name+'-context-registration.json');save(reference,context)
    command=['E:/nodejs/node.exe',str(probe.resolve()),str(gui),str(host),str(OUT/name)]
    result=subprocess.run(command,env=env,capture_output=True,encoding='utf-8',errors='strict',timeout=60)
    save(OUT/(name+'-execution.json'),dict(command=command,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,
        context_registration_sha256=file_hash(reference),scope='Zero-model external browser execution'))
    assert result.returncode==0,result.stderr
    value=from_bound_probe(gui,host,probe,reference,OUT/name/'registration.json',OUT/name/'result.json')
    assert not value['clipping_observed'] and value['real_wheel_changed_scroll']
    save(OUT/(name+'-observation.json'),value);values[name]=value
# Existing source-only observation has identical GUI binding but opposite result.
old=from_probe(WORK/'gui',OLD/'S3-clipping/registration.json',OLD/'S3-clipping/result.json')
assert old['source_binding']==values['C_S3']['source_binding'] and old['clipping_observed']
rejected=[]
try:
    from_bound_probe(WORK/'gui',upstream,probe,OUT/'C_S3-context-registration.json',OUT/'C_S3/registration.json',OUT/'C_S3/result.json')
except ValueError as error:rejected.append(dict(case='wrong_actual_entry_host',error=str(error)))
else:raise AssertionError('cross-host observation accepted')
main=host/'harness/main.tsx';before=main.read_bytes()
try:
    main.write_bytes(before+b'\n// changed host')
    try:
        from_bound_probe(WORK/'gui',host,probe,OUT/'C_S3-context-registration.json',OUT/'C_S3/registration.json',OUT/'C_S3/result.json')
    except ValueError as error:rejected.append(dict(case='changed_host_bytes',error=str(error)))
    else:raise AssertionError('changed host accepted')
finally:main.write_bytes(before)
verify(host,frozen)
assert manifest(upstream)==original and manifest(WORK/'gui/src')==current_source
ab=read(OLD/'component-source-ab/result.json')
assert ab['identical_original_tests'] and not ab['introduced_failure_names']
baseline=dict(kind='historical_component_baseline_observation_v1',
    receipt=dict(path=str(OLD/'component-source-ab/result.json'),sha256=file_hash(OLD/'component-source-ab/result.json')),
    identical_original_tests=True,measurements=[dict(label=r['label'],passed=r['passed'],failed=r['failed'],
        original_test_hashes=r['original_test_hashes'],tested_source_manifest=r['source_manifest']) for r in ab['results']],
    persistent_failure_names=ab['persistent_failure_names'],introduced_failure_names=[],
    test_source_scope='Original tests restored in each audit copy; these manifests are tested copies, not full original candidate GUI identity',
    defect_classification='not_established_by_failure_name_comparison',full_project_regression=False)
save(OUT/'component-baseline-observation.json',baseline)
save(OUT/'result.json',dict(model_calls=0,paid_development_started=False,new_browser_executions=2,
    current_context_observations_passed=True,rejected=rejected,original_source_only_ambiguity_reproduced=True,
    original_fixture_and_business_source_unchanged=True,default_path_changed=False,
    baseline_receipts_reused=True,component_suites_rerun=False,source_only_history_not_upgraded=True,
    prior_unknown_usage_preserved=True,formal_BC_started=False,whole_goal_achieved=False,
    scope='Opt-in host and applicability correction only; not development completion or WSC vs native benefit',
    next_step='Attach these facts symmetrically in separately versioned B/C registration; verify receiver admission without rerunning full development'))
print(json.dumps(dict(model_calls=0,browser_executions=2,S2_clipped=values['S2']['clipping_observed'],C_S3_clipped=values['C_S3']['clipping_observed'],rejected=rejected),ensure_ascii=False))
