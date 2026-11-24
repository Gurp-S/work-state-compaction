"""New-source replay bridge: exact review, no name guessing, bounded original output."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.contracts import digest
from wsc.csm import CSM,CSMError,Event
from wsc.csm.cem.entity_registry import EntityRegistry
from wsc.csm.cem.property_journal import PropertyJournal
from wsc.csm.cem.proposal_bridge import ProposalBridge
from wsc.csm.cem.property_projection import project
from wsc.csm.cem.semantic_contract import PropertySpec,SourceSpan
from test_csm_source_inspection import MemoryStore


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.store=MemoryStore();self.addCleanup(self.store.db.close)
        self.core=CSM(self.store,clock=lambda:'2026-01-02T00:00:00Z')
        self.turn={'dia_id':'t1','speaker':'Keeper','text':'Keeper has companions A and B.',
                   'img_url':['original-url'],'blip_caption':'source description','extra':{'keep':[1,2]}}
        self.core.ingest([Event('new','source_processing_replay',{'date':'original date, timezone unknown','turns':[self.turn]},
                               observed_at='2026-01-01T00:00:00Z')])
        EntityRegistry(self.core).initialize();journal=PropertyJournal(self.core);journal.initialize()
        self.spec=PropertySpec('test:members/v1','set','OWNED_BY','object')
        journal.register(self.spec,evidence=(SourceSpan('new',('turns',0,'text'),self.turn['text']),))
        self.bridge=ProposalBridge(self.core,event_id='new',spec_key=self.spec.key,processing_scope='test')
        span={'turn_id':'t1','field':'text'}
        self.data={'entities':[{'key':'new:'+key,'label':label,'source':span} for key,label in
            [('owner','Keeper'),('a','A'),('b','B')]],'changes':[{'owner':'new:owner','operation':'create','coverage':'partial',
            'source':span,'members':[{'ref':'new:a','source':span},{'ref':'new:b','source':span}]}]}

    def apply(self):
        return self.bridge.apply_review(json.dumps(self.data),expected_digest=digest(self.data),
            entity_keys=['new:owner','new:a','new:b'],change_indices=[0],reviewer='explicit-offline-fixture',reason='Caller reviewed source roles.')

    def test_new_receipt_commits_only_after_explicit_review(self):
        before=self.store.db.total_changes
        parsed=self.bridge.validate(json.dumps(self.data))
        self.assertEqual(self.data,parsed);self.assertEqual(before,self.store.db.total_changes)
        result=self.apply();head=result['commits'][0]['head']
        self.assertEqual('2026-01-01T00:00:00Z',head['valid_from'])
        self.assertIn('not_original_event_time',result['time_basis'])
        self.assertEqual(2,len(head['value']))

    def test_wrong_digest_and_unknown_ref_do_not_create_entities(self):
        with self.assertRaisesRegex(CSMError,'digest_mismatch'):
            self.bridge.apply_review(json.dumps(self.data),expected_digest='wrong',entity_keys=['new:owner'],
                change_indices=[],reviewer='x',reason='x')
        self.data['changes'][0]['members'][0]['ref']='not-offered'
        with self.assertRaisesRegex(CSMError,'ref_not_offered'):self.bridge.validate(json.dumps(self.data))
        self.assertEqual(0,self.store.db.execute('SELECT count(*) FROM csm_entities').fetchone()[0])

    def test_duplicate_json_or_source_field_is_rejected(self):
        with self.assertRaisesRegex(CSMError,'duplicate_key'):
            self.bridge.validate('{"entities":[],"entities":[],"changes":[]}')
        self.data['entities'][0]['source']={'turn_id':'absent','field':'text'}
        with self.assertRaisesRegex(CSMError,'span_invalid'):self.bridge.validate(json.dumps(self.data))

    def test_old_event_without_new_receipt_is_not_silently_migrated(self):
        self.core.ingest([Event('old','chat',{'turns':[self.turn]})])
        with self.assertRaisesRegex(CSMError,'new_receipt_required'):
            ProposalBridge(self.core,event_id='old',spec_key=self.spec.key,processing_scope='test')

    def test_exact_review_replay_does_not_add_revisions_or_relations(self):
        first=self.apply()
        before={t:self.store.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
                ('csm_entities','revisions','csm_property_commits','csm_property_relation_events')}
        again=self.apply()
        self.assertFalse(again['commits'][0]['changed'])
        self.assertEqual(first['commits'][0]['head']['value'],again['commits'][0]['head']['value'])
        self.assertEqual(before,{t:self.store.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})

    def test_projection_preserves_complete_source_record_and_unknown_total(self):
        result=self.apply();key=result['commits'][0]['binding']['binding_key']
        packet=project(self.core,key)
        self.assertEqual(['A','B'],[m['label'] for m in packet['members']])
        self.assertEqual(self.turn,packet['sources'][0]['value']['turns'][0])
        self.assertIsNone(packet['world_total']);self.assertFalse(packet['confirmed'])
        self.assertLessEqual(len(json.dumps(packet,ensure_ascii=False,separators=(',',':'))),4000)

    def test_projection_limits_whole_members_and_reports_omissions(self):
        result=self.apply();key=result['commits'][0]['binding']['binding_key']
        packet=project(self.core,key,max_members=1)
        self.assertEqual(1,packet['published_members']);self.assertEqual(1,packet['omitted_members'])
        self.assertTrue(packet['truncated']);self.assertEqual(self.turn,packet['sources'][0]['value']['turns'][0])

    def test_projection_never_truncates_long_original_body_to_fit(self):
        self.turn['img_url']=['x'*6000]
        # Separate fresh source: integrity checks remain real; no sealed source is rewritten.
        self.core.ingest([Event('huge','source_processing_replay',{'turns':[self.turn]},observed_at='2026-01-01T00:00:00Z')])
        self.bridge=ProposalBridge(self.core,event_id='huge',spec_key=self.spec.key,processing_scope='huge')
        result=self.apply();key=result['commits'][0]['binding']['binding_key']
        with self.assertRaisesRegex(CSMError,'metadata_exceeds_budget'):project(self.core,key,max_chars=4000)


if __name__=='__main__':unittest.main()
