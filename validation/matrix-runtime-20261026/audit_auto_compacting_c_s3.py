"""Close one actual S3 qualification; historical C comparison is descriptive."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, manifest, digest
AREA = Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
OLD = Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
p, r, prep = (read(AREA/name) for name in ('phase-journal.json','result.json','prepared.json'))
supp = read(AREA/'supplemental-grade.json')
old = read(OLD/'phase-journal.json')
reg = prep['registration']
work = Path(reg['workspace'])
assert p['completed'] and p['usage_complete'] and not p['failure'] and p['finals']
assert r['native_and_cumulative_checks_passed'] and r['pins_unchanged'] and r['cleanup']['empty_confirmed']
assert not r['ledger']['study']['uncertain'] and not r['ledger']['inflight']
assert file_hash(AREA/'closed-native.jsonl') == p['rollout_sha256']
source = manifest(work/'gui/src')
assert source == read(AREA/'S3-acceptance/registration.json')['source_manifest']
assert supp['source_unchanged'] and supp['concurrency']['passed'] and supp['scope']['passed']
assert not supp['clipping']['clipping_observed'] and supp['clipping']['source_unchanged'] and not supp['clipping']['errors']
assert all(row['exit_code']==0 and row['cleanup']['empty_confirmed'] for row in supp['drivers'])
assert len(r['automatic_checks']) == 11 and all(row['passed'] for row in r['automatic_checks'])
assert len(supp['concurrency']['outcomes']) == len(supp['scope']['checks']) == 3
assert file_hash(AREA/'package.json') == read(OLD/'prepared.json')['package_sha256']
assert prep['request'] == read(OLD/'prepared.json')['request']
assert reg['initial_manifest'] == read(OLD/'prepared.json')['registration']['initial_manifest']
receipts = p['receipts']['response_receipts']
compactors = set(p['receipts']['compactor_response_ids'])
assert len(receipts)==62 and len(compactors)==2
transitions = []
for i, row in enumerate(receipts):
    if row['response_id'] in compactors:
        assert i>0 and i+1<len(receipts)
        transitions.append(dict(compaction_response_id=row['response_id'], compaction_usage=row['usage'],
            before_input=receipts[i-1]['usage']['input_tokens'], after_input=receipts[i+1]['usage']['input_tokens']))
changes = [name for name, value in reg['initial_manifest'].items() if file_hash(work/name)!=value]
assert all(name.startswith('gui/src/') for name in changes)
new_usage, old_usage = p['receipts']['all_usage'], old['receipts']['all_usage']
new_uncached = new_usage['input_tokens']-new_usage['cached_input_tokens']
old_uncached = old_usage['input_tokens']-old_usage['cached_input_tokens']
audit = dict(scope='S2->S3 C qualification only, not full eight-stage task or formal B/C',
    qualification_passed=True, native_completed=True, usage_complete=True, independent_checks_passed=17,
    production_host_scroll_passed=True, source_unchanged_during_grading=True, GUI_sha256=digest(source),
    known_usage=new_usage, uncached_input_tokens=new_uncached, responses=62, normal_responses=60,
    seconds=p['seconds'], compaction_usage=p['receipts']['compaction_usage'], compactions=transitions,
    changed_source_files={name:file_hash(work/name) for name in changes},
    initial_manifest_restored=True, original_request_and_package_reused=True,
    historical_C_observation=dict(known_usage=old_usage, uncached_input_tokens=old_uncached,
        responses=old['receipts']['response_count'], seconds=old['seconds'], completed=old['completed'], usage_complete=old['usage_complete'],
        known_token_delta_percent=100*(new_usage['total_tokens']/old_usage['total_tokens']-1),
        uncached_input_delta_percent=100*(new_uncached/old_uncached-1),
        output_delta_percent=100*(new_usage['output_tokens']/old_usage['output_tokens']-1),
        observed_stage_seconds_delta_percent=100*(p['seconds']/old['seconds']-1),
        causal_effect_proven=False, interpretation='Two historical C observations, single trials; old complete usage unknown. No B, repeated-trial or timing-ablation inference.'),
    WSC_semantic_advantage_over_native_proven=False, whole_campaign_usage_complete=False,
    full_project_build_or_original_component_suite_proven=False,
    inputs_sha256={name:file_hash(AREA/name) for name in ('registration.json','experiment-intervention.json',
        'prepared.json','package.json','phase-journal.json','result.json','closed-native.jsonl',
        'S2-restoration.json','supplemental-grade-registration.json','supplemental-grade.json')})
save(AREA/'closed-review.json',audit)
print({k:audit[k] for k in ('qualification_passed','independent_checks_passed','GUI_sha256','uncached_input_tokens','seconds','compactions')})
