"""Budgeted source-backed names and whole original records for a journal binding."""
import json
from types import SimpleNamespace
from ..contracts import digest
from .contracts import require
from .entity_registry import require_entity, _label
from .property_journal import PropertyJournal, _snapshot, _ConnectionView, _spec


def project(service, binding_key, *, max_chars=4000, max_members=15):
    require(type(max_chars)is int and max_chars>=512,'property_projection_budget_invalid')
    require(type(max_members)is int and 0<max_members<=15,'property_projection_limit_invalid')
    with _snapshot(service.store) as db:
        view=PropertyJournal(SimpleNamespace(store=_ConnectionView(db))).inspect(binding_key)
        require(_spec(db,view['binding']['property_key'])['spec']['cardinality']=='set','property_projection_set_required')
        owner=view['binding']['owner_ref']
        owner_name=_label(db,require_entity(db,owner)['entity_id'])
        members=[]
        for ref in view['head']['value']:
            name=_label(db,require_entity(db,ref)['entity_id'])
            relation=view['active_members'][ref]
            members.append({'entity_ref':ref,'label':name['label'],'relation_kind':relation['kind'],
                'owner_role':relation['owner_role'],'source_spans':relation['evidence']+name['evidence']})
        total=len(members);members=members[:max_members]
        while True:
            proofs=[*owner_name['evidence'],*(s for m in members for s in m['source_spans'])]
            sources={}
            for proof in proofs:
                event=db.execute('SELECT data,digest FROM events WHERE id=?',(proof['event_id'],)).fetchone()
                require(event is not None,'evidence_source_unknown')
                payload=json.loads(event['data']);require(digest(payload)==event['digest'],'evidence_source_digest_mismatch')
                path=proof['path']
                if len(path)>=2 and path[0]=='turns' and type(path[1])is int:
                    index=path[1];key=(proof['event_id'],index)
                    unit={k:v for k,v in payload.items() if k!='turns'}
                    unit['turns']=[payload['turns'][index]]
                    scope='dialogue_turn'
                else:key=(proof['event_id'],None);unit=payload;scope='observed_event'
                sources[key]={'event_id':proof['event_id'],'source_scope':scope,'value':unit}
            rows=[]
            for member in members:
                rows.append({**{k:v for k,v in member.items() if k!='source_spans'},
                    'source_paths':[{'event_id':s['event_id'],'path':s['path']} for s in member['source_spans']]})
            packet={'policy':'reviewed-source-property-projection-v1',
                'owner':{'entity_ref':owner,'label':owner_name['label']},'property_key':view['binding']['property_key'],
                'identity_revision':view['head']['revision'],'members':rows,'sources':list(sources.values()),
                'time_basis':'new_source_receipt_time_not_original_event_time',
                'state_scope':'known_source_claims_not_world_latest_or_exhaustive',
                'semantic_support':'caller_reviewed_not_independently_verified','confirmed':False,
                'world_total':None,'completeness':'not_established','published_members':len(rows),
                'omitted_members':total-len(rows),'truncated':total!=len(rows),'max_chars':max_chars}
            if len(json.dumps(packet,ensure_ascii=False,separators=(',',':')))<=max_chars:return packet
            require(bool(members),'property_projection_metadata_exceeds_budget')
            members.pop()
