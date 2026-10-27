"""Opt-in lossless selection metadata projection, without semantic filtering.

All public text, source order, model records and selectable spans survive. Cold
locators move to a sealed readable manifest; short IDs remain citation handles.
"""
from copy import deepcopy
from pathlib import Path
import json
from wsc.contracts import encode,digest,require
from wsc.resource_io import ResourceIO

DEFAULTS={'call_id':None,'observed_at':None,'text_in_frontier':True,'public_text_available':True}
FACT_COLUMNS=('automatically_retained','serialized_record_bytes','public_text_utf8_bytes')


def transport_value(value):
    """Freeze the actual JSON domain before dispatch, not Python tuple identity."""
    return json.loads(encode(value))


def transport_equal(actual,expected):
    # Python equality conflates False with 0; canonical JSON keeps their types.
    return encode(actual)==encode(expected)


def project(offered,destination):
    wire=deepcopy(offered);events=wire['events'];cold={};aliases={}
    for event in events:
        alias=event['id'];locator=event['cold_source']
        require(alias not in cold,'selection_wire_alias_ambiguous')
        for identity in (alias,locator['source_id']):
            require(identity not in aliases or aliases[identity]==alias,'selection_wire_identity_ambiguous')
            aliases[identity]=alias
        cold[alias]=deepcopy(locator)
        event['cold_source']={'manifest_key':alias}
    reference_originals=[]
    def remap(parent,key,path,*,many):
        if key not in parent:return
        old=deepcopy(parent[key]);values=old if many else [old]
        require(isinstance(values,(list,tuple)) and all(type(value) is str and value in aliases for value in values),'selection_wire_previous_source_not_bound')
        mapped=[aliases[value] for value in values]
        parent[key]=mapped if many else mapped[0]
        reference_originals.append({'path':path+[key],'value':old})
    previous=wire.get('previous_selection',{})
    remap(previous,'source_ids',['previous_selection'],many=True)
    for i,clue in enumerate(previous.get('clues',[])):remap(clue,'sources',['previous_selection','clues',i],many=True)
    for i,excerpt in enumerate(wire.get('previous_excerpts',[])):remap(excerpt,'source_id',['previous_excerpts',i],many=False)
    defaults={key:value for key,value in DEFAULTS.items() if events and all(key in event for event in events)}
    for event in events:
        for key,value in defaults.items():
            if event[key]==value and type(event[key]) is type(value):event.pop(key)
    wire['event_defaults']=defaults
    facts=wire.get('selection_facts',{})
    if 'source_records' in facts:
        records=facts.pop('source_records')
        require(all(set(value)==set(FACT_COLUMNS) for value in records.values()),'selection_wire_fact_shape_unknown')
        facts['source_record_table']={'columns':['source',*FACT_COLUMNS],
            'rows':[[key,*[value[column] for column in FACT_COLUMNS]] for key,value in records.items()]}
    manifest={'format':'wsc.selection_resources/1','cold_sources':cold}
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    ResourceIO().write_once(destination,encode(manifest).encode('utf-8'))
    wire['cold_source_manifest']={'path':str(destination),'sha256':digest(manifest),'format':manifest['format'],
        'entries':'cold_sources keyed by event id; each entry retains original path, SHA256, source identity and observation time.'}
    bindings={'format':'wsc.selection_wire_binding/1','original_sha256':digest(offered),'wire_sha256':digest(wire),
        'manifest_sha256':digest(manifest),'aliases':aliases,'original_source_aliases':list(cold),'reference_originals':reference_originals}
    require(restore(wire,manifest,bindings)==offered,'selection_wire_roundtrip_changed')
    return wire,manifest,bindings


def restore(wire,manifest,bindings):
    require(digest(wire)==bindings['wire_sha256'] and digest(manifest)==bindings['manifest_sha256'],'selection_wire_binding_changed')
    result=deepcopy(wire);defaults=result.pop('event_defaults');result.pop('cold_source_manifest')
    for event in result['events']:
        require(event['cold_source']=={'manifest_key':event['id']},'selection_wire_locator_changed')
        event['cold_source']=deepcopy(manifest['cold_sources'][event['id']])
        for key,value in defaults.items():event.setdefault(key,value)
    facts=result.get('selection_facts',{})
    if 'source_record_table' in facts:
        table=facts.pop('source_record_table');require(table['columns']==['source',*FACT_COLUMNS],'selection_wire_columns_changed')
        facts['source_records']={row[0]:dict(zip(FACT_COLUMNS,row[1:])) for row in table['rows']}
    for entry in bindings.get('reference_originals',[]):
        parent=result
        for key in entry['path'][:-1]:parent=parent[key]
        parent[entry['path'][-1]]=deepcopy(entry['value'])
    require(digest(result)==bindings['original_sha256'],'selection_wire_roundtrip_changed')
    return result


def normalize_draft(draft,bindings):
    """Translate only typed citation fields; prose, scope and revisions untouched."""
    result=deepcopy(draft)
    def aliases(values):
        require(isinstance(values,list) and all(type(v) is str and v in bindings['aliases'] for v in values),'selection_wire_source_not_offered')
        return [bindings['aliases'][value] for value in values]
    result['source_ids']=aliases(result.get('source_ids',[]))
    for field in ('new_understandings','clues'):
        for record in result.get(field,[]):record['sources']=aliases(record['sources'])
    return result
