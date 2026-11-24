"""Exercise actual benchmark routing and renderers, without any model calls."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'benchmarks'))
import evidence_adapter as evidence
import csm_locomo_plus as locomo
import csm_public_exam as public


def rows(n=8):
    return [{'memory_id':f'person:slot{i}', 'entity':'person', 'slot':f'slot{i}',
             'value':f'Fact {i}', 'status':'current'} for i in range(n)]


def source_packet():
    return {'items':[{'memory_id':'event:source', 'record_type':'source_event',
        'value':{'date':'13 October 2023','turns':[{'speaker':'person','text':'Original observation.'}]},
        'classification':'UNKNOWN','source_refs':['source'],'confirmed':False}],
        'policy':'source-evidence-v2','max_chars':4000,'max_items':6,'truncated':False,'omitted':0}


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.service = SimpleNamespace(recall_evidence=Mock(side_effect=lambda *a,**k:source_packet()))

    def test_default_fuses_all_primary_winners_without_changing_them(self):
        primary = rows(45); original = json.loads(json.dumps(primary))
        result = evidence.fuse(self.service,'a question',primary)
        self.assertEqual(result.primary,original)
        self.assertEqual(list(result)[:45],original)
        self.assertEqual(primary,original)
        self.assertEqual(result[-1]['memory_id'],'event:source')

    def test_wide_v18_v24_execute_under_fusion(self):
        primary = rows(45)
        os.environ.update(WSC_LOCOMO_RETRIEVE_WIDE='1',WSC_LOCOMO_V18='1',WSC_LOCOMO_V24='1')
        corpus={r['memory_id']:r['value'] for r in primary}
        refs={r['memory_id']:['session'] for r in primary}
        with patch.object(locomo,'candidate_pool',return_value=primary), \
             patch.object(locomo,'_corpus',return_value=corpus), \
             patch.object(locomo,'_session_index',return_value=(refs,{'session':list(corpus)})), \
             patch.object(locomo.ranker,'normalize_query',return_value='normalized') as normalize, \
             patch.object(locomo.ranker,'document_frequency',return_value={}), \
             patch.object(locomo.ranker,'rank',return_value=primary):
            fused=locomo.qa_context(self.service,None,{'question':'question','category':4},['person'])
            self.assertEqual(len(fused.primary),45)
            self.assertTrue(normalize.called)
            os.environ['WSC_CSM_EVIDENCE_PIPELINE']='0'
            legacy=locomo.qa_context(self.service,None,{'question':'question','category':4},['person'])
            self.assertEqual(fused.primary,legacy)

    def test_multihop_is_executed_before_supplement(self):
        os.environ['WSC_LOCOMO_V21']='1'
        primary=rows(10)
        with patch.object(locomo,'candidate_pool',return_value=primary), \
             patch.object(locomo,'_corpus',return_value={}), \
             patch.object(locomo,'_session_index',return_value=({},{})), \
             patch.object(locomo.locomo_multihop,'resolve',return_value={'items':primary}) as resolve:
            result=locomo.qa_context(self.service,None,{'question':'question','category':1},['person'])
        resolve.assert_called_once()
        self.assertEqual(result.primary,primary)

    def test_common_sense_trigger_is_executed_before_supplement(self):
        os.environ['WSC_LOCOMO_V23']='1'
        primary=rows(6)
        with patch.object(locomo,'trigger_context',return_value=primary) as trigger, \
             patch.object(locomo,'_retrieve_legacy') as fallback:
            result=locomo.qa_context(self.service,None,{'question':'question','category':3},['person'])
        trigger.assert_called_once();fallback.assert_not_called()
        self.assertEqual(result.primary,primary)

    def test_event_dates_and_legacy_rendering_survive_fusion(self):
        packet=source_packet()
        packet['items'].append({'memory_id':'technical-head','record_type':'memory',
            'value':'hurt last month','valid_from':'2026-11-04T00:00:00Z'})
        self.service.recall_evidence.side_effect=lambda *a,**k:packet
        primary=[{'memory_id':'injury','entity':'person','slot':'injury','value':'hurt last month',
                  'valid_from':'2026-11-04T00:00:00Z'}]
        with patch.dict(locomo._DATES,{'injury':'13 October 2023'},clear=True), \
             patch.dict(locomo._HAPPENED,{'injury':'September 2023'},clear=True):
            legacy=json.loads(locomo.render(primary))
            fused=json.loads(locomo.render(evidence.fuse(self.service,'injury',primary)))
        self.assertEqual(fused['items'][:1],legacy)
        self.assertEqual(fused['items'][0]['said_on'],'13 October 2023')
        self.assertIn('September 2023',fused['items'][0]['value'])
        self.assertNotIn('2026',json.dumps(fused))

    def test_conflicting_source_only_flags_fail_before_chat_or_ingestion(self):
        os.environ.update(WSC_CSM_EVIDENCE_PIPELINE='source-only',WSC_LOCOMO_V21='1')
        with patch.object(locomo,'Chat') as chat:
            with self.assertRaisesRegex(ValueError,'bypass'):
                locomo.run_qa(0,Path('unused.json'),Path('unused.db'))
        chat.assert_not_called()

    def test_inactive_wide_features_are_rejected_before_chat(self):
        os.environ['WSC_LOCOMO_V18']='1'
        with patch.object(locomo,'Chat') as chat:
            with self.assertRaisesRegex(ValueError,'RETRIEVE_WIDE'):
                locomo.run_qa(0,Path('unused.json'),Path('unused.db'))
        chat.assert_not_called()

    def test_disabled_source_lane_does_not_call_new_recall(self):
        os.environ['WSC_CSM_EVIDENCE_PIPELINE']='0'
        primary=rows()
        with patch.object(locomo,'_retrieve_legacy',return_value=primary):
            result=locomo.retrieve(self.service,'question',['person'])
        self.assertIs(result,primary)
        self.service.recall_evidence.assert_not_called()

    def test_prefilter_pilot_passes_lane_and_primary_exclusions_to_allocator(self):
        with patch.dict(os.environ, {"WSC_CSM_SUPPLEMENT_PREFILTER": "1"}):
            evidence.fuse(self.service, "question", rows(2))
        kwargs = self.service.recall_evidence.call_args.kwargs
        self.assertEqual(kwargs["record_types"], ("source_event", "pending"))
        self.assertEqual(set(kwargs["exclude_ids"]), {r["memory_id"] for r in rows(2)})

    def test_public_router_keeps_primary_and_adds_sources(self):
        self.service.search=Mock(return_value={'results':rows(3)})
        result=public.retrieve(self.service,'question',[],{'entities':[],'topics':[]})
        self.assertEqual(len(result.primary),3)
        self.assertEqual(result[-1]['record_type'],'source_event')
        packet=json.loads(public.render(result))
        self.assertTrue(packet['primary_preserved'])
        self.assertEqual(packet['primary_count'],3)

    def test_legacy_routing_understands_new_pending_rows_without_confirmation(self):
        pending={'pending_id':'proposal','entity':'person','slot':'description',
                 'proposed':{'value':'an unresolved interpretation'},'source_refs':['source']}
        self.service.search=Mock(return_value={'results':[pending]})
        context=public.retrieve(self.service,'question',[],{'entities':[],'topics':[]})
        item=json.loads(public.render(context))['items'][0]
        self.assertEqual(item['value'],'an unresolved interpretation')
        self.assertEqual(item['classification'],'PENDING_BINDING')
        self.assertFalse(item['confirmed'])
        context=locomo.retrieve(self.service,'question',[])
        item=json.loads(locomo.render(context))['items'][0]
        self.assertEqual(item['classification'],'PENDING_BINDING')
        self.assertFalse(item['confirmed'])

    def test_real_run_entry_prepares_triggers_when_fusion_enabled(self):
        os.environ['WSC_LOCOMO_V23']='1'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            (root/'data/locomo10.json').write_text(json.dumps([{'qa':[{'question':'question','category':3,'answer':'a','evidence':[]}]}]),encoding='utf-8')
            chat=SimpleNamespace(calls=0,ask=Mock(return_value='answer'))
            with patch.object(locomo,'BENCH',root),patch.object(locomo,'Chat',return_value=chat), \
                 patch.object(locomo,'CSM',return_value=self.service),patch.object(locomo,'CsmStore'), \
                 patch.object(locomo,'ingest_conversation',return_value=['person']), \
                 patch.object(locomo,'prepare_triggers') as prepare, \
                 patch.object(locomo,'trigger_context',return_value=rows(6)), \
                 patch.object(locomo,'judge',return_value={'label':'correct','reason':'fixture'}), \
                 patch.object(locomo,'_RERANK',None):
                locomo.run_qa(0,root/'out.json',root/'unused.db')
            prepare.assert_called_once()
            record=json.loads((root/'out.json').read_text(encoding='utf-8'))['records'][0]
            self.assertEqual(len(record['primary_retrieved']),6)
            self.assertEqual(record['supplement_retrieved'],['event:source'])

    def test_pending_target_identity_does_not_shadow_a_confirmed_memory(self):
        proposal={'pending_id':'proposal','memory_id':'person:fact',
                  'operation':'REKEY','classification':'PENDING_BINDING'}
        normalized=list(evidence.candidate_rows([proposal]))[0]
        self.assertEqual(normalized['memory_id'],'proposal')
        self.assertEqual(normalized['record_type'],'pending')
        self.assertFalse(normalized['confirmed'])

    def test_deferred_ingestion_keeps_original_dates_without_confirming_it(self):
        date='13 October 2023'
        sample={'conversation':{'session_1_date_time':date,'session_1':[
            {'dia_id':'turn','speaker':'person','text':'I was injured last month.'}]}}
        candidate={'entity':'person','slot':'injury','value':'injured last month','topics':[]}
        self.service.ingest=Mock()
        self.service.remember=Mock(return_value=[{'operation':'DEFER','memory_id':None,'pending_id':'proposal'}])
        with patch.object(locomo,'cached_extract',return_value=[candidate]), \
             patch.object(locomo,'resolve_relative',return_value={'injury':'September 2023'}), \
             patch.object(locomo,'_load_cache',return_value={}), \
             patch.object(locomo,'_save_cache'), \
             patch.dict(locomo._DATES,{},clear=True),patch.dict(locomo._HAPPENED,{},clear=True):
            locomo.ingest_conversation(self.service,None,sample,'fixture')
            pending=list(evidence.candidate_rows([{'pending_id':'proposal','proposed':candidate}]))
            rendered=json.loads(locomo.render(pending))[0]
        self.assertEqual(rendered['said_on'],date)
        self.assertIn('September 2023',rendered['value'])
        self.assertFalse(rendered['confirmed'])

    def test_multihop_gap_recovery_accepts_pending_without_promoting_it(self):
        self.service.search=Mock(return_value={'results':[{'pending_id':'proposal',
            'proposed':{'value':'injury'},'source_refs':['source']}]})
        plan={'anchors':[],'requirements':['injury'],'budget':2,'query_mode':'fixture'}
        with patch.object(locomo.locomo_multihop,'plan',return_value=plan):
            result=locomo.locomo_multihop.resolve(self.service,'injury',[],pool=[])
        self.assertEqual(result['items'][0]['memory_id'],'proposal')
        self.assertFalse(result['items'][0]['confirmed'])

    def test_trigger_preparation_accepts_pending_without_losing_its_content(self):
        os.environ['WSC_LOCOMO_V23']='1'
        self.service.query=Mock(return_value={'results':[{'pending_id':'proposal',
            'proposed':{'value':'injury'},'source_refs':['source']}]})
        with patch.dict(locomo._TRIGGERS,{},clear=True),patch.dict(locomo._TRIGGER_ITEMS,{},clear=True), \
             patch.object(locomo,'_load_cache',return_value={}),patch.object(locomo,'_save_cache'), \
             patch.object(locomo.locomo_trigger,'derive_triggers',return_value={}) as derive:
            locomo.prepare_triggers(None,self.service,['person'])
            item=derive.call_args.args[1][0]
        self.assertEqual(item['value'],'injury')
        self.assertEqual(item['classification'],'PENDING_BINDING')
        self.assertFalse(item['confirmed'])


if __name__ == '__main__':unittest.main()
