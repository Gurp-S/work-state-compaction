"""Close the paid trial and record zero-model baseline/host causal diagnostics."""
from pathlib import Path
import json,sys
from collections import Counter
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,manifest,digest
AREA=Path('D:/agent-task-runs/wsc-a3-dev-C-incremental-20261026-v1')
WORK=Path('D:/agent-task-runs/wsc-a3-select-scoped-20261026-v1/workspace')
r=read(AREA/'result.json');phase=read(AREA/'phase-journal.json');reg=read(AREA/'registration.json')
assert r['cleanup']['empty_confirmed'] and r['pins_unchanged'] and not r['ledger']['inflight']
assert r['failure']=='registered_token_cap' and not r['usage_complete']
assert r['ledger']['study']['uncertain'] and not phase['finals']
source=manifest(WORK/'gui/src')
assert source==read(AREA/'S3-acceptance/registration.json')['source_manifest']
for folder in ('S3-concurrency','S3-scope','S3-clipping','S3-production-shell-clipping'):
 assert source==read(AREA/folder/'registration.json')['source_manifest']
 assert read(AREA/folder/'result.json')['source_unchanged']
assert read(AREA/'S3-concurrency/result.json')['passed'] and read(AREA/'S3-scope/result.json')['passed']
assert read(AREA/'S3-clipping/result.json')['clipping_observed']
assert not read(AREA/'S3-production-shell-clipping/result.json')['clipping_observed']
assert read(AREA/'S3-production-shell-clipping/result.json')['changedScroll']
assert not read(AREA/'S2-production-shell-clipping/result.json')['clipping_observed']
assert read(AREA/'S2-production-shell-clipping/result.json')['changedScroll']
component=read(AREA/'component-source-ab/result.json')
assert not component['introduced_failure_names'] and len(component['persistent_failure_names'])==9
commands=[];first=None
for line in (AREA/'S3-phase/events.jsonl').read_text(encoding='utf-8').splitlines():
 try:event=json.loads(line)
 except ValueError:continue
 if first is None and event.get('emittedAtMs'):first=event['emittedAtMs']
 if event.get('method')!='item/completed':continue
 item=event.get('params',{}).get('item',{})
 if item.get('type')!='commandExecution':continue
 command=item.get('command','')
 kind='component_test' if 'vitest' in command else 'browser_acceptance' if 'run-acceptance.mjs' in command and 'node.exe' in command else 'typecheck' if 'tsc' in command and 'node.exe' in command else 'other'
 commands.append(dict(category=kind,command=command,status=item.get('status'),exit_code=item.get('exitCode'),seconds_from_event_origin=round((event['emittedAtMs']-first)/1000,3)))
before=reg['session']['initial_manifest'];after=r['source_manifest_after']
code_changes=[name for name in sorted(set(before)|set(after)) if name.startswith('gui/src/') and before.get(name)!=after.get(name)]
assert len(code_changes)==7
assert all(before.get(k)==after.get(k) for k in before if k.startswith('task-contract/'))
review=dict(native_completed=False,failure=r['failure'],known_usage=phase['receipts']['all_usage'],
    known_responses=phase['receipts']['response_count'],seconds=phase['seconds'],complete_usage=None,
    whole_campaign_usage_complete=False,cleanup_empty=True,pins_unchanged=True,
    independent_functional_passes=17,official_passes=11,concurrency_passes=3,selection_scope_passes=3,
    source_gui_sha256=digest(source),source_manifest=source,code_changes=code_changes,
    frozen_contract_unchanged=True,known_chain=dict(tokens=222309+70588+phase['receipts']['all_usage']['total_tokens'],responses=49,
       scope='Last scoped selection plus incremental revision plus this C development only; historical whole campaign remains unknown'),
    component_baseline_AB=dict(identical_original_tests=True,baseline=dict(passed=27,failed=9),candidate=dict(passed=27,failed=9),
       introduced_failures=[],scope='Original two component suites only; not a claim all failures are test defects'),
    host_AB=dict(original_host_clipped=True,actual_component_wrapper_host_clipped=False,
       actual_component_wrapper_S2_clipped=False,real_wheel_scrolls_in_both_wrapped_versions=True,
       sole_host_change='UsagePageBody to existing A3SnapshotPanel with PageShell',
       production_source_changed_for_diagnostic=False,frozen_acceptance_modified=False,
       full_application_visual_qualification=False,
       corrected_interpretation='The registered inner-body host clips; this observation does not prove the production entry lacks scrolling. GUI-source binding alone omits execution host/entry applicability.'),
    public_command_counts=dict(Counter(c['category'] for c in commands)),public_commands=commands,
    observed_cost_issue='Broad component retesting chased failures already present on S2; this does not attribute all tokens or prove a BC causal difference.',
    full_C_qualification_passed=False,BC_started=False,BC_benefit_proven=False,
    next_step='Calibrate opt-in experiment host/entry and baseline receipts with zero model calls before any further development or formal BC; preserve original failures and unknowns.')
save(AREA/'closed-review.json',review)
print(json.dumps({k:review[k] for k in ('known_responses','seconds','independent_functional_passes','source_gui_sha256','code_changes','known_chain','public_command_counts')},ensure_ascii=False))
