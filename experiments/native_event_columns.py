"""Opt-in homogeneous event columns, preserving every original span and field."""
from copy import deepcopy
from native_metadata_columns import vector,expand,MAX_ROWS
from wsc.contracts import encode,digest,require

FORMAT='wsc.event_columns/1'


def project(material):
    result=deepcopy(material);events=result['events'];applied=False
    require(type(events) is list and all(type(e) is dict for e in events),'event_columns_events_invalid')
    if events and len(events)<=MAX_ROWS:
        fields=sorted(events[0])
        if all(sorted(e)==fields for e in events):
            table=dict(format=FORMAT,event_count=len(events),fields=fields,columns=[vector([e[k] for e in events]) for k in fields])
            if len(encode(table).encode())<len(encode(events).encode()):result['events']=table;applied=True
    binding=dict(format='wsc.event_columns_binding/1',applied=applied,original_sha256=digest(material),represented_sha256=digest(result))
    require(encode(restore(result,binding))==encode(material),'event_columns_roundtrip_changed')
    return result,binding


def restore(material,binding):
    require(binding.get('format')=='wsc.event_columns_binding/1' and type(binding.get('applied')) is bool and digest(material)==binding['represented_sha256'],'event_columns_binding_changed')
    result=deepcopy(material)
    if binding['applied']:
        table=result['events']
        require(type(table) is dict and set(table)=={'format','event_count','fields','columns'} and table['format']==FORMAT,'event_columns_shape_invalid')
        count=table['event_count'];fields=table['fields'];columns=table['columns']
        require(type(count) is int and 0<count<=MAX_ROWS and type(fields) is list and all(type(k) is str for k in fields) and len(fields)==len(set(fields)) and type(columns) is list and len(columns)==len(fields),'event_columns_fields_invalid')
        values=[expand(c,count) for c in columns]
        result['events']=[dict(zip(fields,row)) for row in zip(*values)] if fields else [{} for _ in range(count)]
    require(digest(result)==binding['original_sha256'],'event_columns_roundtrip_changed')
    return result
