"""Literal search has no write authority and shares the revision-read budget."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src'), str(Path(__file__).resolve().parents[1]/'benchmarks')]
import test_csm_source_tools as fixture
from wsc.csm.cem.source_tools import SourceToolSession
from wsc.csm.cem.source_search_tools import SourceSearchSession
import source_tool_loop


class SourceSearchTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SourceToolTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def session(self, until=None):
        return SourceSearchSession(SourceToolSession(self.case.core,self.case.primary,until=until))

    def test_search_and_revision_read_share_two_reads_and_no_writes(self):
        session=self.session();before=self.case.store.db.total_changes
        result=json.loads(session.execute('search_source_evidence','{"query":"hurt"}'))
        self.assertIn('got hurt',json.dumps(result));session.execute('csm_read_source','{"handle":"r1"}')
        self.assertEqual(2,session.reads);self.assertLessEqual(session.used_chars,4000)
        with self.assertRaisesRegex(ValueError,'read_limit'):session.execute('search_source_evidence','{"query":"setback"}')
        self.assertEqual(before,self.case.store.db.total_changes)

    def test_future_sources_are_not_searchable_before_cutoff(self):
        result=json.loads(self.session('2025-12-01T00:00:00Z').execute('search_source_evidence','{"query":"hurt"}'))
        self.assertEqual([],result['result']['items'])

    def test_extra_arguments_and_repeated_queries_are_neutral_errors(self):
        session=self.session()
        self.assertIn('error',json.loads(session.execute('search_source_evidence','{"query":"hurt","sql":"x"}')))
        session=self.session();session.execute('search_source_evidence','{"query":"hurt"}')
        self.assertIn('repeated',json.loads(session.execute('search_source_evidence','{"query":"HURT"}'))['error'])

    def test_flag_off_preserves_old_catalogue_and_on_dispatches_declared_search(self):
        with patch.dict(os.environ,{'WSC_CSM_SOURCE_SEARCH':'0'}):
            old,_=source_tool_loop.prepare(self.case.core,self.case.primary,self.case.rendered)
            self.assertIsInstance(old,SourceToolSession)
        response=fixture.call(name='search_source_evidence')
        response['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"query":"hurt"}'
        chat=fixture.FakeChat([response,fixture.final()])
        with patch.dict(os.environ,{'WSC_CSM_SOURCE_SEARCH':'1'}):
            answer=self.case.run_loop(chat)
        self.assertEqual(1,answer['source_tool']['source_reads'])
        self.assertEqual({'csm_read_source','search_source_evidence'},
                         {t['function']['name'] for t in chat.requests[0]['tools']})

    def test_oversized_declared_batch_returns_errors_without_reading_or_raising_budget(self):
        response=fixture.call();calls=[]
        for index in range(4):
            call=fixture.call(call_id='batch-'+str(index))['choices'][0]['message']['tool_calls'][0]
            calls.append(call)
        response['choices'][0]['message']['tool_calls']=calls
        chat=fixture.FakeChat([response,fixture.final()])
        with patch.dict(os.environ,{'WSC_CSM_SOURCE_SEARCH':'1','WSC_CSM_SOURCE_BATCH_ERRORS':'1'}), \
             patch.object(self.case.core,'source_evidence') as read:
            result=self.case.run_loop(chat)
        read.assert_not_called()
        self.assertEqual(0,result['source_tool']['source_reads'])
        self.assertLessEqual(result['source_tool']['source_chars'],4000)
        self.assertEqual(4,len(result['source_tool']['reads']))
        self.assertTrue(all(not r['executed'] for r in result['source_tool']['reads']))
