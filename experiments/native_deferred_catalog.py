"""Optional snapshot metadata deferral, with a one-result feasibility guard."""
from copy import deepcopy
from native_event_columns import project as columns,restore as restore_columns
from native_metadata_columns import project as budgets,restore as restore_budgets,vector,expand,MAX_ROWS
from wsc.contracts import encode,digest,require

FORMAT='wsc.deferred_catalog/1'


def reply(payload,*,calls,catalog_calls):
    count=payload['source_count']
    return dict(status='ok',catalog=deepcopy(payload),catalog_sha256=digest(payload),
        storage_validation='not_performed; sealed snapshot metadata only',
        metrics=dict(calls=calls,catalog_calls=catalog_calls,metadata_sources_checked=count,permission_checks_this_call=2*count,physical_disk_bytes=None))


def project(material,*,max_return_bytes=16384,max_calls=8,max_sources=8192):
    original=deepcopy(material);result=deepcopy(original);events=original['events']
    require(type(events) is list and all(type(e) is dict for e in events),'deferred_events_invalid')
    cold=[(i,e) for i,e in enumerate(events) if e.get('text_in_frontier') is False and e.get('public_text_available') is False and e.get('spans')==[]]
    facts=original.get('selection_facts',{}).get('source_record_table');payload=None;internals=None;reason='no_cold_events_or_table'
    if cold and type(facts) is dict and set(facts)=={'columns','rows'}:
        aliases=[row[0] for row in facts['rows']]
        require(aliases==[e['id'] for e in events] and len(set(aliases))==len(aliases),'deferred_source_order_changed')
        if len(aliases)<=max_sources:
            raw=dict(events=[e for _,e in cold],selection_facts={'source_record_table':facts})
            first,event_binding=columns(raw);packed,budget_binding=budgets(first)
            snapshot=dict(session_id=original['session_id'],cut=original['frontier_boundary']['current_cut'],source_digest=original['frontier_boundary']['source_digest'])
            candidate=dict(format=FORMAT,snapshot=snapshot,event_count=len(events),source_count=len(aliases),
                cold_positions=vector([i for i,_ in cold]),material=packed)
            size_probe=reply(candidate,calls=max_calls,catalog_calls=max_calls)
            if len(encode(size_probe).encode())<=max_return_bytes:
                payload=candidate;internals=dict(events=event_binding,budgets=budget_binding)
                indices={i for i,_ in cold}
                result['events']=[deepcopy(e) for i,e in enumerate(events) if i not in indices]
                result['visible_event_positions']=[i for i,e in enumerate(events) if i not in indices]
                result['selection_facts'].pop('source_record_table')
                result['selection_facts']['source_record_table_ref']='historical_catalog.material.selection_facts.source_record_table'
                result['historical_catalog']=dict(format=FORMAT,sha256=digest(payload),cold_events=len(cold),total_events=len(events),operation='WSCSource.catalog',
                    observation_scope='Sealed snapshot metadata, not current storage health; current read permission checked on catalog access.')
                reason='applied'
            else:reason='catalog_exceeds_single_result_budget'
        else:reason='catalog_exceeds_metadata_scan_budget'
    binding=dict(format='wsc.deferred_catalog_binding/1',applied=payload is not None,reason=reason,
        original_sha256=digest(original),represented_sha256=digest(result),catalog_sha256=digest(payload) if payload else None,internals=internals)
    require(encode(restore(result,payload,binding))==encode(original),'deferred_roundtrip_changed')
    return result,payload,binding


def decoded_catalog(payload,binding):
    require(type(payload) is dict and payload.get('format')==FORMAT and digest(payload)==binding['catalog_sha256'],'deferred_catalog_changed')
    raw=restore_columns(restore_budgets(payload['material'],binding['internals']['budgets']),binding['internals']['events'])
    count=len(raw['selection_facts']['source_record_table']['rows'])
    require(type(payload['source_count']) is int and payload['source_count']==count,'deferred_aliases_changed')
    aliases=[r[0] for r in raw['selection_facts']['source_record_table']['rows']]
    return raw,aliases


def restore(material,payload,binding):
    require(binding.get('format')=='wsc.deferred_catalog_binding/1' and type(binding.get('applied')) is bool and digest(material)==binding['represented_sha256'],'deferred_binding_changed')
    result=deepcopy(material)
    if binding['applied']:
        raw,_=decoded_catalog(payload,binding);positions=expand(payload['cold_positions'],len(raw['events']))
        hot=result.pop('visible_event_positions');total=payload['event_count']
        require(type(total) is int and 0<=total<=MAX_ROWS and type(hot) is list,'deferred_count_invalid')
        all_events=[None]*total;used=set()
        for index,event in [*zip(positions,raw['events']),*zip(hot,result['events'])]:
            require(type(index) is int and 0<=index<total and index not in used,'deferred_position_invalid')
            used.add(index);all_events[index]=deepcopy(event)
        require(len(used)==total and len(hot)==len(result['events']),'deferred_position_missing')
        result['events']=all_events;result.pop('historical_catalog');result['selection_facts'].pop('source_record_table_ref')
        result['selection_facts']['source_record_table']=raw['selection_facts']['source_record_table']
    else:require(payload is None,'deferred_unused_catalog')
    require(digest(result)==binding['original_sha256'],'deferred_roundtrip_changed')
    return result
