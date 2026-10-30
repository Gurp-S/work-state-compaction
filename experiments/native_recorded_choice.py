"""Strict first-frontier draft reuse; no new selection, scope edits or CAS repair."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from wsc.contracts import encode,require
from wsc.resource_io import ResourceIO
from native_incremental_candidate import compile_draft,POLICY
from native_incremental_compile import compile_choice
from native_selection_wire import normalize_draft
from native_span_handles import expand


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def reuse(core,snapshot,source):
    source=Path(source);generation=source/'C-selector/generation'
    phase=read(source/'coordinator-private/C/selection/phase-outcome.json')
    require(phase.get('completed') and phase.get('usage_complete') and not phase.get('failure')
        and len(phase.get('finals',[]))==1,'recorded_choice_phase_incomplete')
    rollout=source/'coordinator-private/C/selection/rollout.jsonl'
    require(sha256(rollout.read_bytes()).hexdigest()==phase['rollout_sha256'],'recorded_choice_rollout_changed')
    original=json.loads(phase['finals'][0]['text'])
    require(encode(original)==encode(read(generation/'model-draft.json')),'recorded_choice_response_changed')
    bindings=read(generation/'wire-bindings.json')
    draft=expand(normalize_draft(original,bindings),read(generation/'span-handle-bindings.json'))
    require(encode(draft)==encode(read(generation/'compiled-draft.json')),'recorded_choice_compilation_changed')
    manifest_path=generation/'resource-manifest.json';raw=manifest_path.read_bytes();manifest=read(manifest_path)
    manifest_sha=sha256(raw).hexdigest()
    require(bindings['manifest_sha256']==manifest_sha,'recorded_choice_manifest_changed')
    material=core.material(snapshot);locators=manifest['cold_sources'];events=material['events']
    require(len(locators)==len(events),'recorded_choice_source_count_changed')
    io=ResourceIO()
    for event in events:
        alias='s'+str(event['seq']);locator=locators.get(alias)
        require(locator is not None and locator['source_id']==event['id']
            and encode(locator['observed_at'])==encode(event['observed_at']),'recorded_choice_source_binding_changed')
        value=io.read_bounded(locator['path'],POLICY['max_material_bytes']+1)
        require(sha256(value).hexdigest()==locator['sha256'] and value==encode(event).encode('utf-8'),
            'recorded_choice_source_bytes_changed')
    require(not draft['understanding_refs'] and not draft['retained_excerpt_keys'],'recorded_choice_history_not_supported')
    selection=compile_choice(material,None,draft,compile_draft)
    package=read(source/'coordinator-private/C/publication.json')['package']
    records_path=Path(package['understanding_index']);records_raw=records_path.read_bytes()
    require(sha256(records_raw).hexdigest()==package['understanding_index_sha256'],'recorded_choice_record_index_changed')
    records=json.loads(records_raw)
    imported=[];used=set()
    for record in selection.new_understandings:
        require(record.scope=={'source_manifest_sha256':manifest_sha},'recorded_choice_scope_not_exact')
        matches=[r for r in records if encode({k:r[k] for k in ('text','kind','scope','sources')})==encode(
            dict(text=record.text,kind=record.kind,scope=record.scope,sources=record.sources))]
        require(len(matches)==1,'recorded_choice_record_not_unique');old=matches[0]
        require(type(old['revision']) is int and old['revision']==1 and old['previous'] is None and old['producer']==POLICY['id']
            and old['id'] not in used and record.id in (None,old['id']) and record.expected_revision is None,
            'recorded_choice_record_revision_unsupported')
        used.add(old['id']);imported.append(replace(record,id=old['id']))
    require(len(used)==len(records),'recorded_choice_record_set_changed')
    selection=replace(selection,new_understandings=tuple(imported))
    return selection,dict(source=str(source),source_manifest_sha256=manifest_sha,verified_sources=len(events),
        imported_record_ids=sorted(used),scope_unchanged=True,model_calls=0,
        original_selection_usage=phase['receipts']['all_usage'],
        scope='Historical model-authored draft reused only after exact source-byte, scope and recorded-identity verification. Not a new selection call.')
