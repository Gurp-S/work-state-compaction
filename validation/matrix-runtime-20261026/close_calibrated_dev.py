"""Closed-trial public-action and response accounting; no model reasoning used."""
from pathlib import Path
from collections import Counter
from contextlib import closing
import json,sys,re
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,manifest,digest
from native_campaign_envelope import qualification_envelope
AREA=Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
r=read(AREA/'result.json');phase=read(AREA/'phase-journal.json');registration=read(AREA/'registration.json')
assert r['cleanup']['empty_confirmed'] and r['pins_unchanged'] and not r['ledger']['inflight']
assert r['failure']=='registered_token_cap' and not r['usage_complete'] and not phase['finals']
work=Path(registration['session']['workspace'])
current=manifest(work/'gui/src');assert current==read(AREA/'S3-acceptance/registration.json')['source_manifest']
for name in ('S3-concurrency','S3-scope','S3-clipping'):
 assert current==read(AREA/name/'registration.json')['source_manifest']
 assert read(AREA/name/'result.json')['source_unchanged']
assert read(AREA/'S3-concurrency/result.json')['passed'] and read(AREA/'S3-scope/result.json')['passed']
assert not read(AREA/'S3-clipping/result.json')['clipping_observed']
receipts=phase['receipts']['response_receipts'];inputs=[x['usage']['input_tokens'] for x in receipts]
first_reference=len(inputs)*inputs[0]
rows=[json.loads(l) for l in (AREA/'closed-native.jsonl').read_text(encoding='utf-8').splitlines()]
public=rows[phase['turn_accounting']['before']['records']:]
outputs=[];calls={}
for row in public:
 v=row.get('payload',{})
 if row['type']!='response_item':continue
 if v.get('type')=='custom_tool_call':calls[v['call_id']]=v.get('input','')
 if v.get('type') in ('custom_tool_call_output','function_call_output'):
  data=v.get('output');text='\n'.join(x.get('text','') for x in data if isinstance(x,dict)) if isinstance(data,list) else str(data)
  outputs.append(dict(call_id=v.get('call_id'),bytes=len(text.encode()),truncated='Warning: truncated output' in text,
    header=text[:200]))
commands=[]
for line in (AREA/'S3-phase/events.jsonl').read_text(encoding='utf-8').splitlines():
 try:event=json.loads(line)
 except ValueError:continue
 if event.get('method')!='item/completed':continue
 item=event.get('params',{}).get('item',{})
 if item.get('type')!='commandExecution':continue
 c=item.get('command','')
 # Execution classification excludes reads/globs that merely contain a tool name.
 kind='component_test_execution' if re.search(r'vitest(?:[\\/]|\.mjs|\s+run)',c) else 'browser_acceptance_execution' if 'run-acceptance.mjs' in c and 'node.exe' in c else 'build_execution' if ('vite.js' in c or 'vite ' in c) and 'build' in c else 'other'
 commands.append(dict(kind=kind,status=item.get('status'),command=c))
before=registration['session']['initial_manifest'];after=r['source_manifest_after']
code_changes=[k for k in sorted(set(before)|set(after)) if k.startswith('gui/src/') and before.get(k)!=after.get(k)]
frozen=Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace')
assert file_hash(frozen/'gui/vite.config.ts')==file_hash(work/'gui/vite.config.ts')
assert not (frozen/'gui/pet.html').exists() and not (work/'gui/pet.html').exists()
review=dict(native_completed=False,known_usage=phase['receipts']['all_usage'],known_responses=len(receipts),seconds=phase['seconds'],
 complete_usage=None,whole_campaign_usage_complete=False,independent_functional_passes=17,production_host_clipping=False,
 source_gui_sha256=digest(current),code_changes=code_changes,source_unchanged_during_independent_checks=True,
 cleanup_empty=True,pins_unchanged=True,compaction_response_ids=phase['receipts']['compactor_response_ids'],
 input_growth=dict(first=inputs[0],last=inputs[-1],mean=sum(inputs)/len(inputs),
  constant_first_input_reference=first_reference,growth_above_constant_first_reference=sum(inputs)-first_reference,
  interpretation='Arithmetic reference only, not avoidable tokens or a semantics-preserving compaction prediction'),
 public_command_counts=dict(Counter(c['kind'] for c in commands)),public_commands=commands,
 visible_tool_text=dict(total_bytes=sum(o['bytes'] for o in outputs),outputs=len(outputs),truncated_outputs=sum(o['truncated'] for o in outputs),
  largest=sorted(outputs,key=lambda o:o['bytes'],reverse=True)[:8],
  note='Actual outer tool-output text, not raw inner stdout; no token attribution inferred from byte counts'),
 memory_read_call_ids=[key for key,value in calls.items() if '\\memories\\' in value or 'memories/' in value],
 inherited_build_evidence=dict(vite_config_unchanged=True,frozen_and_current_pet_entry_missing=True,
  baseline_build_rerun=False,full_GUI_build_qualified=False,
  observed_errors=['native .vite-temp write EPERM','runner config __dirname undefined','missing pet.html entry']),
 evidence_use_observation='No original component suite execution observed this run; does not prove calibration alone caused the difference',
 hypothesis_not_proven='New calibration facts suffice to deliver normally under the existing arm cap',
 design_implication='Boundary-only selection is followed by substantial live-stage input growth; examine bounded live projection/compaction capability before more paid development',
 full_C_qualification_passed=False,formal_BC_started=False,BC_benefit_proven=False,
 next_step='Stop paid repeats; inspect native mid-stage control and output-coverage contract, then version a structural proposal before implementation')
assert review['public_command_counts'].get('component_test_execution',0)==0
save(AREA/'closed-review.json',review)
envelope=qualification_envelope(r['ledger'],[],phase['seconds'])
envelope.update(whole_campaign_usage_complete=False,old_unknowns_preserved=True,parent_result=dict(path=str(AREA/'result.json'),sha256=file_hash(AREA/'result.json')))
save(AREA/'next-admission-envelope.json',envelope)
print({k:review[k] for k in ('known_responses','seconds','input_growth','public_command_counts','source_gui_sha256')})
