"""Explicitly reviewed model proposals for NEW source-processing replay stores.

No model calls, automatic name equivalence, semantic approval, old-store adoption,
or inferred historical timezone. State time is the new source receipt time.
"""
import json
import re

from ..contracts import digest
from .contracts import MemoryCandidate, require, parse_instant
from .entity_registry import EntityRegistry
from .property_journal import PropertyJournal
from .semantic_contract import SourceSpan, PropertyBinding, RelationClaim

TOOL = 'propose_relationship_changes'


class ProposalBridge:
    def __init__(self, service, *, event_id, spec_key, processing_scope):
        require(isinstance(processing_scope, str) and bool(processing_scope), 'bridge_scope_missing')
        self.service, self.event_id, self.spec_key = service, event_id, spec_key
        self.contexts = ('source_processing:' + processing_scope,)
        with service.store.connect() as db:
            event = db.execute('SELECT source_type,observed_at,data,digest FROM events WHERE id=?', (event_id,)).fetchone()
            require(event is not None and event['source_type'] == 'source_processing_replay', 'bridge_new_receipt_required')
            require(bool(event['observed_at']), 'bridge_receipt_time_missing')
            parse_instant(event['observed_at'])
            self.observed_at = event['observed_at']
            self.payload = json.loads(event['data'])
            require(digest(self.payload) == event['digest'], 'evidence_source_digest_mismatch')
        self.turns = {t['dia_id']: i for i,t in enumerate(self.payload.get('turns', [])) if isinstance(t,dict) and t.get('dia_id')}
        require(len(self.turns) == len(self.payload.get('turns', [])), 'bridge_turn_ids_invalid')
        self.registry, self.journal = EntityRegistry(service), PropertyJournal(service)

    def span(self, item):
        require(isinstance(item,dict) and set(item) == {'turn_id','field'}, 'bridge_span_fields_invalid')
        require(item['turn_id'] in self.turns and item['field'] in ('text','speaker','blip_caption'), 'bridge_span_invalid')
        index = self.turns[item['turn_id']]
        text = self.payload['turns'][index].get(item['field'])
        require(isinstance(text,str) and bool(text.strip()), 'bridge_span_missing')
        return SourceSpan(self.event_id, ('turns',index,item['field']), text)

    def catalogue(self):
        with self.service.store.connect() as db:
            refs = ['entity:' + r[0] for r in db.execute('SELECT entity_id FROM csm_entities ORDER BY rowid')]
        require(len(refs) <= 16, 'bridge_entity_catalogue_limit')
        return [{'ref': ref, 'label': self.registry.get(ref)['current_label']['label']} for ref in refs]

    @staticmethod
    def definition():
        span = {'type':'object','properties':{'turn_id':{'type':'string'},'field':{'type':'string','enum':['text','speaker','blip_caption']}},
                'required':['turn_id','field'],'additionalProperties':False}
        return {'type':'function','function':{'name':TOOL,
            'description':'Uncommitted source relationship proposals. References denote listed entities or new local keys. Source claims retain incomplete coverage.',
            'parameters':{'type':'object','properties':{
                'entities':{'type':'array','maxItems':16,'items':{'type':'object','properties':{
                    'key':{'type':'string','description':'New local reference, new:<key>.'},'label':{'type':'string'},'source':span},
                    'required':['key','label','source'],'additionalProperties':False}},
                'changes':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
                    'owner':{'type':'string'},'operation':{'type':'string','enum':['create','set_add','set_remove','replace']},
                    'coverage':{'type':'string','enum':['partial','source_claimed_complete']},'source':span,
                    'members':{'type':'array','maxItems':16,'items':{'type':'object','properties':{
                        'ref':{'type':'string'},'source':span},'required':['ref','source'],'additionalProperties':False}}},
                    'required':['owner','operation','coverage','source','members'],'additionalProperties':False}}},
                'required':['entities','changes'],'additionalProperties':False}}}

    def validate(self, arguments):
        require(isinstance(arguments,str) and len(arguments)<=10000, 'bridge_arguments_budget')
        def unique(pairs):
            out={}
            for k,v in pairs:
                require(k not in out,'bridge_duplicate_key');out[k]=v
            return out
        data=json.loads(arguments,object_pairs_hook=unique)
        require(isinstance(data,dict) and set(data)=={'entities','changes'},'bridge_arguments_invalid')
        require(isinstance(data['entities'],list) and len(data['entities'])<=16 and
                isinstance(data['changes'],list) and len(data['changes'])<=8,'bridge_items_limit')
        known={r['ref'] for r in self.catalogue()};local=set()
        for e in data['entities']:
            require(isinstance(e,dict) and set(e)=={'key','label','source'},'bridge_entity_fields_invalid')
            require(isinstance(e['key'],str) and re.fullmatch(r'new:[A-Za-z][A-Za-z0-9_-]{0,23}',e['key']) is not None
                    and e['key'] not in local,'bridge_local_ref_invalid')
            require(isinstance(e['label'],str) and bool(e['label'].strip()),'bridge_entity_label_missing')
            self.span(e['source']);local.add(e['key'])
        for c in data['changes']:
            require(isinstance(c,dict) and set(c)=={'owner','operation','coverage','source','members'},'bridge_change_fields_invalid')
            require(c['owner'] in known|local,'bridge_ref_not_offered')
            require(c['operation'] in ('create','set_add','set_remove','replace') and c['coverage'] in ('partial','source_claimed_complete'),
                    'bridge_operation_invalid')
            self.span(c['source'])
            require(isinstance(c['members'],list) and len(c['members'])<=16,'bridge_items_limit')
            refs=[]
            for m in c['members']:
                require(isinstance(m,dict) and set(m)=={'ref','source'} and m['ref'] in known|local,'bridge_ref_not_offered')
                self.span(m['source']);refs.append(m['ref'])
            require(len(refs)==len(set(refs)),'bridge_duplicate_member')
        return data

    def apply_review(self, arguments, *, expected_digest, entity_keys, change_indices, reviewer, reason):
        data=self.validate(arguments)
        require(digest(data)==expected_digest,'bridge_review_digest_mismatch')
        require(isinstance(reviewer,str) and bool(reviewer.strip()) and isinstance(reason,str) and bool(reason.strip()),
                'bridge_review_attribution_missing')
        keys={e['key'] for e in data['entities']}
        require(len(entity_keys)==len(set(entity_keys)) and set(entity_keys)<=keys,'bridge_review_selection_invalid')
        require(len(change_indices)==len(set(change_indices)) and all(type(i)is int and 0<=i<len(data['changes']) for i in change_indices),
                'bridge_review_selection_invalid')
        resolved={r['ref']:r['ref'] for r in self.catalogue()};created=[];commits=[]
        for e in data['entities']:
            if e['key'] not in entity_keys:continue
            result=self.registry.create(request_id=self.event_id+'/'+e['key'],label=e['label'],evidence=(self.span(e['source']),),producer=reviewer)
            resolved[e['key']]=result['ref'];created.append(result)
        for index in change_indices:
            c=data['changes'][index]
            require(c['owner'] in resolved and all(m['ref'] in resolved for m in c['members']),'bridge_unreviewed_entity')
            request_id=self.event_id+'/change/'+str(index)
            review_reason=reason+'; raw_model_arguments_digest='+expected_digest
            with self.service.store.connect() as db:
                saved=db.execute('SELECT proposal_id,digest FROM csm_property_proposals WHERE request_id=?',(request_id,)).fetchone()
                review=db.execute('SELECT data FROM csm_property_reviews WHERE proposal_id=?',(saved['proposal_id'],)).fetchone() if saved else None
            if saved:
                require(review is not None,'bridge_review_recovery_required')
                previous_review=json.loads(review['data'])
                require(previous_review['decision']=='accepted' and previous_review['reviewer']==reviewer
                        and previous_review['reason']==review_reason,'bridge_review_conflict')
                commits.append(self.journal.commit(saved['proposal_id'],expected_digest=saved['digest'],producer=reviewer))
                continue
            owner=resolved[c['owner']]
            key=digest({'owner':owner,'property':self.spec_key,'contexts':self.contexts})
            with self.service.store.connect() as db:
                row=db.execute('SELECT memory_id FROM csm_property_bindings WHERE binding_key=?',(key,)).fetchone()
            previous=self.journal.inspect(key) if row else None
            source=self.span(c['source'])
            binding=PropertyBinding(owner,contexts=self.contexts,memory_id=previous['binding']['memory_id'] if previous else None,
                expected_revision=previous['head']['revision'] if previous else None,
                expected_value=previous['head']['value'] if previous else None,evidence=(source,))
            candidate=MemoryCandidate(owner,self.spec_key,[resolved[m['ref']] for m in c['members']],contexts=self.contexts,
                source_ids=(self.event_id,),expected_revision=binding.expected_revision,valid_from=self.observed_at)
            claims=tuple(RelationClaim('OWNED_BY',resolved[m['ref']],owner,'end' if c['operation']=='set_remove' else 'assert',
                (source,self.span(m['source'])),contexts=self.contexts) for m in c['members'])
            proposal=self.journal.propose(request_id=request_id,spec_key=self.spec_key,
                binding=binding,candidate=candidate,operation=c['operation'],relations=claims,coverage=c['coverage'],
                coverage_evidence=(source,) if c['coverage']=='source_claimed_complete' else ())
            self.journal.review(proposal['proposal_id'],expected_digest=proposal['digest'],decision='accepted',reviewer=reviewer,
                reason=review_reason,evidence=(source,))
            commits.append(self.journal.commit(proposal['proposal_id'],expected_digest=proposal['digest'],producer=reviewer))
        return {'arguments_digest':expected_digest,'reviewer':reviewer,'reason':reason,'created_entities':created,'commits':commits,
            'time_basis':'new_source_receipt_time_not_original_event_time','processing_contexts':self.contexts}
