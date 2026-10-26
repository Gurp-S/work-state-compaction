"""Experimental incremental WSC selection; no native calls or task decisions.

Original public sources stay immutable. The generator sees new public text,
old source handles, selected prior model records and selectable prior excerpts.
Only model choices determine semantic retention. No automatic whole-message
carry, summary nesting, inferred relevance or claim of current applicability.
"""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.contracts import Limits, Usage, digest, encode, require
from wsc.content_archive import publish_object
from wsc.excerpts import Excerpt
from wsc.quote_selection import SelectionDraft
from wsc.span_selection import span_material, compile_spans
from wsc.selection_facts import describe
from wsc.view_budget import admit_generation

POLICY = dict(id='incremental_recorded_spans_v2', max_material_bytes=2097152,
    max_view_body_bytes=131072, max_rendered_bytes=49152, max_chars_per_span=1024,
    span_boundary_policy='word', generation_attempts_per_boundary=1,
    preserve_user_control_sources=True, semantic_status='unverified')


def reference_aliases(material):
    """Every displayed exact identity denotes one source; ambiguity is rejected."""
    aliases = {}
    for event in material['events']:
        short = f"s{event['seq']}"
        for value in (short, event['id']):
            require(value not in aliases or aliases[value] == short, 'incremental_source_identity_ambiguous')
            aliases[value] = short
    return aliases


def compile_draft(material, draft):
    aliases = reference_aliases(material)
    def exact(values):
        require(isinstance(values, (list, tuple)) and all(isinstance(v, str) and v in aliases for v in values),
                'incremental_source_reference_not_offered')
        return [aliases[v] for v in values]
    value = dict(draft)
    value['source_ids'] = exact(value.get('source_ids', []))
    for field in ('new_understandings', 'clues'):
        values = value.get(field, [])
        require(isinstance(values, list) and all(isinstance(v, dict) for v in values), 'incremental_record_list_invalid')
        value[field] = [{**record, 'sources': exact(record.get('sources', []))} for record in values]
    return compile_spans(material, value, max_chars=POLICY['max_chars_per_span'], boundary_policy='word')


def frontier(core, snapshot, previous, archive):
    original = core.material(snapshot)
    admit_generation(snapshot.events, POLICY['max_view_body_bytes'])
    cut = previous['cut'] if previous else 0
    require(type(cut) is int and 0 <= cut <= snapshot.cut, 'incremental_previous_cut_invalid')
    if previous:
        require(previous['session_id'] == snapshot.session_id and previous['workspace'] == snapshot.workspace
                and previous['source_digest'] == digest(list(snapshot.events[:cut])), 'incremental_previous_binding_changed')
    records = {r['ref']: r for r in original['understandings']}
    selected_refs = previous['understanding_refs'] if previous else []
    require(len(selected_refs) == len(set(selected_refs)) and set(selected_refs) <= records.keys(),
            'incremental_previous_record_missing')
    previous_selection = {'source_ids': [], 'clues': []}
    if previous:
        with core.store.connect() as db:
            saved = db.execute('SELECT data FROM views WHERE id=?', (previous.get('view_id'),)).fetchone()
        require(saved is not None, 'incremental_previous_view_missing')
        saved = json.loads(saved[0])
        require(saved['binding']['cut'] == cut and saved['binding']['source_digest'] == previous['source_digest'],
                'incremental_previous_view_binding_changed')
        body = saved['body']
        require([r['ref'] for r in body['understandings']] == selected_refs,
                'incremental_previous_record_selection_changed')
        require({item['key'] for item in body.get('excerpts', [])} == {item['key'] for item in previous['excerpts']},
                'incremental_previous_excerpt_selection_changed')
        previous_selection = {'source_ids': [r['id'] for r in body['sources']], 'clues': body['clues']}
    archive = Path(archive).resolve()
    archive.mkdir(parents=True, exist_ok=True)
    events = []
    for event in original['events']:
        payload = encode(event).encode('utf8')
        key = digest(event)
        path = archive / (key + '.json')
        publish_object(path, payload)
        events.append({**event, 'text': event['text'] if event['seq'] > cut else None,
            'text_in_frontier': event['seq'] > cut,
            'cold_source': {'path': str(path), 'sha256': sha256(payload).hexdigest(),
                            'source_id': event['id'], 'observed_at': event['observed_at']}})
    prior_excerpts = previous['excerpts'] if previous else []
    by_id = {r['id']: r for r in original['events']}
    offered_prior = []
    keys = set()
    for value in prior_excerpts:
        excerpt = Excerpt(**value)
        require(excerpt.key not in keys and excerpt.source_id in by_id and excerpt.basis == 'public_text',
                'incremental_previous_excerpt_invalid')
        keys.add(excerpt.key)
        text = by_id[excerpt.source_id]['text']
        require(isinstance(text, str) and 0 <= excerpt.start < excerpt.end <= len(text),
                'incremental_previous_excerpt_range_changed')
        selected = text[excerpt.start:excerpt.end]
        require(sha256(selected.encode()).hexdigest() == excerpt.text_sha256,
                'incremental_previous_excerpt_text_changed')
        offered_prior.append({**value, 'text': selected, 'observed_at': by_id[excerpt.source_id]['observed_at']})
    material = {**{k: v for k, v in original.items() if k not in ('events', 'understandings')},
        'events': events, 'understandings': [records[key] for key in selected_refs],
        'frontier_boundary': {'previous_cut': cut, 'current_cut': snapshot.cut, 'source_digest': snapshot.source_digest},
        'previous_excerpts': offered_prior,
        'previous_selection': previous_selection,
        'selection_facts': {**describe(snapshot.events, POLICY['max_view_body_bytes']),
            'adapter_rendered_limit_bytes': POLICY['max_rendered_bytes'],
            'adapter_measurement_scope': 'Encoded exported native items; separate from prepared-view storage bytes and model tokens.'},
        'selection_fields': {'source_ids': 'Selected entire original records, including their unchanged payloads.',
            'understanding_refs': 'Selected existing model record revisions.',
            'new_understandings': 'New or explicitly versioned model records with source aliases.',
            'span_refs': 'Selected exact spans of public text available in this frontier.',
            'retained_excerpt_keys': 'Selected previous excerpts, with original source identity, time and text hash.'}}
    reference_aliases(material)
    offered = span_material(material, max_chars=POLICY['max_chars_per_span'], boundary_policy='word')
    require(len(encode(offered).encode()) <= POLICY['max_material_bytes'], 'incremental_material_budget_exhausted')
    return material, offered


def prepare(core, snapshot, previous, archive, generate, *, source_projection=None):
    material, offered = frontier(core, snapshot, previous, archive)
    attempt = 'incremental:' + snapshot.source_digest
    core.begin_usage(attempt, phase='incremental_selection')
    usage = Usage()
    try:
        draft = generate(offered)
        require(isinstance(draft, SelectionDraft) and isinstance(draft.usage, Usage), 'incremental_generation_result_invalid')
        usage = draft.usage
        value = dict(draft.selection)
        retained = value.pop('retained_excerpt_keys', [])
        require(isinstance(retained, list) and all(isinstance(k, str) for k in retained)
                and len(retained) == len(set(retained)), 'incremental_retained_excerpt_keys_invalid')
        known = {item['key']: item for item in (previous['excerpts'] if previous else [])}
        require(set(retained) <= known.keys(), 'incremental_retained_excerpt_missing')
        selection = compile_draft(material, value)
        require(set(selection.understanding_refs) <= {r['ref'] for r in material['understandings']},
                'incremental_record_not_offered')
        combined = (*selection.excerpts, *(Excerpt(**known[key]) for key in retained))
        require(len({e.key for e in combined}) == len(combined), 'incremental_excerpt_key_collision')
        selection = replace(selection, excerpts=combined)
        view = core.prepare(snapshot, selection, producer=POLICY['id'],
            limits=Limits(max_material_bytes=POLICY['max_material_bytes'], max_view_bytes=POLICY['max_view_body_bytes']),
            source_projection=source_projection)
        with core.store.connect() as db:
            body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (view,)).fetchone()[0])['body']
        continuation = dict(session_id=snapshot.session_id, workspace=snapshot.workspace, cut=snapshot.cut,
            source_digest=snapshot.source_digest, understanding_refs=[r['ref'] for r in body['understandings']],
            excerpts=[asdict(e) for e in selection.excerpts], view_id=view, policy=POLICY['id'])
        core.finish_usage(attempt, usage)
        return dict(view=view, continuation=continuation, offered=offered)
    except BaseException as error:
        failed_usage = getattr(error, 'usage', usage)
        core.finish_usage(attempt, failed_usage if isinstance(failed_usage, Usage) else usage, status='failed')
        raise


def admit_rendered(package):
    require(len(encode(package['items']).encode()) <= POLICY['max_rendered_bytes'], 'incremental_rendered_budget_exhausted')
    return package
