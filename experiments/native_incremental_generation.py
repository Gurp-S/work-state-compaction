"""Read-only native selector transport for the frozen incremental policy."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.contracts import Usage
from wsc.quote_selection import SelectionDraft
from native_evidence import save
from native_generation_binding import verify_transcript
from native_rollout_snapshot import capture_rollout
from native_span_handles import project as project_span_handles,expand as expand_span_handles


def output_schema(offered, *, scoped_manifest_bindings=False,source_aliases_only=False):
    def obj(properties):
        return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)
    string = dict(type='string')
    strings = dict(type='array', items=string)
    source_names = list(dict.fromkeys(value for event in offered['events']
        for value in (event['id'], event['cold_source']['source_id'])))
    if source_aliases_only:source_names=[event['id'] for event in offered['events']]
    source_refs = {'$ref':'#/$defs/source_refs'}
    span_refs = [span['ref'] for event in offered['events'] for span in event['spans']]
    prior_keys = [item['key'] for item in offered['previous_excerpts']]
    record_refs = [record['ref'] for record in offered['understandings']]
    record_ids = list(dict.fromkeys([None, *(record['id'] for record in offered['understandings'])]))
    revisions = list(dict.fromkeys([None, *(record['revision'] for record in offered['understandings'])]))
    scope_properties = dict(source_manifest_sha256=string)
    if scoped_manifest_bindings:
        scope_properties.update(manifest_scope=string, delivery_stage=string)
    schema = obj(dict(source_ids=source_refs, understanding_refs=dict(type='array',
        items=dict(type='string', enum=record_refs) if record_refs else string,
        **({} if record_refs else dict(maxItems=0))),
        new_understandings=dict(type='array', items=obj(dict(
            id=dict(type=['string', 'null'], enum=record_ids),
            expected_revision=dict(type=['integer', 'null'], enum=revisions),
            text=string, kind=string, sources=source_refs,
            scope={**obj(scope_properties), 'type': ['object', 'null']}))),
        clues=dict(type='array', items=obj(dict(text=string, sources=source_refs))),
        span_refs=dict(type='array', items=dict(type='string', enum=span_refs) if span_refs else string,
                       **({} if span_refs else dict(maxItems=0))),
        retained_excerpt_keys=dict(type='array', items=dict(type='string', enum=prior_keys) if prior_keys else string,
                                  **({} if prior_keys else dict(maxItems=0)))))
    schema['$defs']={'source_refs':dict(type='array',items=dict(type='string',enum=source_names))}
    return schema


def generate(offered, execute, destination, *, short_span_handles=False, scoped_manifest_bindings=False,compact_wire=False,source_access=None,cold_event_table=False,metadata_columns=False,event_columns=False,deferred_catalog=None):
    """execute(request, schema) owns cumulative grants and records native spend."""
    if event_columns and cold_event_table:raise ValueError('event_representation_modes_conflict')
    if deferred_catalog is not None and (not compact_wire or cold_event_table or metadata_columns or event_columns):raise ValueError('deferred_representation_modes_conflict')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    if source_access is not None:
        from native_source_tool import checked_description
        description=checked_description(offered,source_access)
        save(destination/'source-access-binding.json',source_access['engine_binding'])
        offered={**offered,'source_access':description}
    bindings=None
    if short_span_handles:
        offered,bindings=project_span_handles(offered)
        save(destination/'span-handle-bindings.json',bindings)
    schema = output_schema(offered, scoped_manifest_bindings=scoped_manifest_bindings,source_aliases_only=compact_wire)
    wire_bindings=None
    if compact_wire:
        from native_selection_wire import project
        offered,manifest,wire_bindings=project(offered,destination/'resource-manifest.json')
        save(destination/'wire-bindings.json',wire_bindings)
    if deferred_catalog is not None:
        offered,catalog,catalog_binding=deferred_catalog.project_material(offered)
        save(destination/'deferred-catalog.json',catalog)
        save(destination/'deferred-catalog-binding.json',catalog_binding)
    if cold_event_table:
        from native_event_table import project as project_event_table
        offered,event_table_binding=project_event_table(offered)
        save(destination/'event-table-binding.json',event_table_binding)
    if metadata_columns:
        from native_metadata_columns import project as project_metadata_columns
        offered,column_binding=project_metadata_columns(offered)
        save(destination/'metadata-column-binding.json',column_binding)
    if event_columns:
        from native_event_columns import project as project_event_columns
        offered,events_binding=project_event_columns(offered)
        save(destination/'event-columns-binding.json',events_binding)
    request = dict(operation='working_state_selection', material=offered,
        generation_scope=dict(role='selection_generation_without_task_execution', model_records='unverified_interpretations',
                              original_sources='historical_observations_with_identity_and_time'))
    if scoped_manifest_bindings:
        request['generation_scope']['scope_format'] = 'manifest_scope_and_delivery_stage_v1'
    from native_selection_wire import transport_value
    request=transport_value(request)
    save(destination / 'request.json', request)
    save(destination / 'schema.json', schema)
    phase, archive = execute(request, schema)
    known = Usage()
    if phase.get('receipts'):
        u = phase['receipts']['all_usage']
        known = Usage(u['input_tokens'] - u['cached_input_tokens'], u['cached_input_tokens'], u['output_tokens'])
    try:
        if not (phase.get('usage_complete') and phase.get('completed') and not phase.get('failure') and len(phase.get('finals', [])) == 1):
            raise ValueError('incremental_native_generation_incomplete')
        snapshot = capture_rollout(archive)
        if snapshot.metadata['sha256'] != phase['rollout_sha256'] or not snapshot.metadata['parse_complete']:
            raise ValueError('incremental_native_generation_archive_changed')
        proof, actual = verify_transcript(snapshot, phase)
        from native_selection_wire import transport_equal
        if not transport_equal(actual,request):
            raise ValueError('incremental_native_generation_request_changed')
        save(destination / 'request-binding.json', proof)
        draft = json.loads(phase['finals'][0]['text'])
        save(destination / 'model-draft.json', draft)
        if wire_bindings is not None:
            from native_selection_wire import normalize_draft
            draft=normalize_draft(draft,wire_bindings)
        if bindings is not None:
            draft=expand_span_handles(draft,bindings)
            save(destination/'compiled-draft.json',draft)
        return SelectionDraft(draft, known)
    except Exception as error:
        error.usage = known
        raise
