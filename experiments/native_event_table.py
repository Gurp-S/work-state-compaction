"""Opt-in reversible cold-event metadata rows; no semantic source filtering."""
from copy import deepcopy
from wsc.contracts import encode,digest,require

FORMAT='wsc.cold_event_rows/1'


def project(material):
    original=deepcopy(material);events=original['events']
    require(type(events) is list and all(type(e) is dict for e in events),'event_table_events_invalid')
    old=[(i,e) for i,e in enumerate(events) if e.get('text_in_frontier') is False]
    result=deepcopy(original);applied=False
    if old:
        keys=sorted(old[0][1])
        if 'event_index' not in keys and all(sorted(e)==keys for _,e in old):
            defaults={k:deepcopy(old[0][1][k]) for k in keys if all(encode(e[k])==encode(old[0][1][k]) for _,e in old)}
            columns=[k for k in keys if k not in defaults]
            table=dict(format=FORMAT,count=len(events),defaults=defaults,row_fields=['event_index',*columns],
                rows=[[i,*[deepcopy(e[k]) for k in columns]] for i,e in old],
                other_events=[dict(event_index=i,event=deepcopy(e)) for i,e in enumerate(events) if e.get('text_in_frontier') is not False])
            if len(encode(table).encode())<len(encode(events).encode()):result['events']=table;applied=True
    binding=dict(format='wsc.event_table_binding/1',applied=applied,original_sha256=digest(original),
        represented_sha256=digest(result),original_events=len(events),cold_events=len(old))
    require(encode(restore(result,binding))==encode(original),'event_table_roundtrip_changed')
    return result,binding


def restore(material,binding):
    require(binding.get('format')=='wsc.event_table_binding/1' and type(binding.get('applied')) is bool,'event_table_binding_invalid')
    require(digest(material)==binding['represented_sha256'],'event_table_binding_changed')
    result=deepcopy(material)
    if binding['applied']:
        table=result['events']
        require(type(table) is dict and set(table)=={'format','count','defaults','row_fields','rows','other_events'} and table['format']==FORMAT,'event_table_shape_invalid')
        count=table['count'];fields=table['row_fields'];defaults=table['defaults'];rows=table['rows'];other=table['other_events']
        require(type(count) is int and count>=0 and type(rows) is list and type(other) is list and count==len(rows)+len(other),'event_table_count_invalid')
        require(type(defaults) is dict and type(fields) is list and fields and fields[0]=='event_index'
            and all(type(k) is str for k in fields) and len(set(fields))==len(fields) and not set(fields[1:])&set(defaults),'event_table_columns_invalid')
        events=[None]*count;used=set()
        def put(index,event):
            require(type(index) is int and 0<=index<count and index not in used,'event_table_position_invalid')
            used.add(index);events[index]=event
        for row in rows:
            require(type(row) is list and len(row)==len(fields),'event_table_row_invalid')
            event={**deepcopy(defaults),**dict(zip(fields[1:],row[1:]))}
            require(event.get('text_in_frontier') is False,'event_table_cold_flag_invalid')
            put(row[0],event)
        for item in other:
            require(type(item) is dict and set(item)=={'event_index','event'} and type(item['event']) is dict,'event_table_other_invalid')
            put(item['event_index'],item['event'])
        require(len(used)==count,'event_table_position_missing');result['events']=events
    require(digest(result)==binding['original_sha256'],'event_table_roundtrip_changed')
    return result
