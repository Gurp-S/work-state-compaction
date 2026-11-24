"""Claims bind host evidence, validate scope, and publish no arbitrary prose."""
import json
from pathlib import Path
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'),
               str(Path(__file__).resolve().parents[1] / 'benchmarks')]
from wsc.csm import CSMError, MemoryCandidate, Event
from wsc.csm.cem.semantic_contract import SourceSpan, PropertyBinding
from wsc.csm.cem.source_claims import SourceClaimSession
import test_csm_proposal_bridge as bridge_fixture
import source_claim_answer


class SourceClaimTests(unittest.TestCase):
    def setUp(self):
        self.fixture = bridge_fixture.BridgeTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        result = self.fixture.apply(); self.key = result['commits'][0]['binding']['binding_key']
        self.core = self.fixture.core
        self.session = SourceClaimSession(self.core, self.key)
        self.refs = [m['entity_ref'] for m in self.session.context()['members']]

    def claim(self, **changes):
        return json.dumps({'projection_ref': 'p1', 'scope': 'source_known_members',
                           'member_refs': self.refs, 'world_total': None, **changes})

    def response(self, *, content='There are exactly two in total.', finish='tool_calls', arguments=None):
        return {'choices': [{'finish_reason': finish, 'message': {'role': 'assistant', 'content': content,
            'tool_calls': [{'id': 'publish-1', 'type': 'function', 'function': {'name': 'publish_source_claim',
                'arguments': arguments or self.claim()}}]}}]}

    def test_supported_member_names_publish_with_total_unknown(self):
        receipt = self.session.publish(self.claim())
        self.assertEqual(['A', 'B'], receipt['member_labels'])
        self.assertIn('complete total is not established', receipt['answer'])
        self.assertIsNone(receipt['world_total']); self.assertFalse(receipt['confirmed'])

    def test_numeric_total_bool_or_string_cannot_publish(self):
        for total in (0, 2, 3, True, '3'):
            with self.subTest(total=total), self.assertRaisesRegex(CSMError, 'world_total_not_established'):
                self.session.publish(self.claim(world_total=total))

    def test_scope_or_extra_prose_cannot_smuggle_claims(self):
        for claim in (self.claim(scope='world_total'), self.claim(answer='Exactly three.'),
                      self.claim(completeness='complete')):
            with self.assertRaises(CSMError): self.session.publish(claim)

    def test_unknown_statement_has_no_member_or_total_assertion(self):
        receipt = self.session.publish(self.claim(scope='unknown', member_refs=[]))
        self.assertEqual([], receipt['member_labels']); self.assertNotIn('"A"', receipt['answer'])
        with self.assertRaisesRegex(CSMError, 'unknown_with_members'):
            self.session.publish(self.claim(scope='unknown'))

    def test_unknown_duplicate_or_omitted_member_is_rejected(self):
        for refs, code in [(['unknown'], 'not_offered'), ([self.refs[0]] * 2, 'duplicate_member'),
                           (self.refs[:1], 'members_omitted')]:
            with self.assertRaisesRegex(CSMError, code): self.session.publish(self.claim(member_refs=refs))

    def test_snapshot_returned_to_caller_cannot_forge_capabilities(self):
        copy = self.session.context(); copy['world_total'] = 2; copy['completeness'] = 'complete'
        copy['members'][0]['label'] = 'unsupported statement'
        receipt = self.session.publish(self.claim())
        self.assertEqual(['A', 'B'], receipt['member_labels']); self.assertIsNone(receipt['world_total'])

    def test_label_change_after_generation_invalidates_snapshot(self):
        registry = self.fixture.bridge.registry
        registry.set_label(self.refs[0], label='Changed label', expected_revision=1,
                           evidence=(self.fixture.bridge.span({'turn_id':'t1','field':'text'}),))
        with self.assertRaisesRegex(CSMError, 'projection_stale'): self.session.publish(self.claim())

    def test_state_change_cannot_publish_stale_data(self):
        current = self.fixture.bridge.journal.inspect(self.key)
        self.core.remember_explicit(MemoryCandidate('x', 'x', [], source_ids=('new',), expected_revision=1),
            operation='replace', target_memory_id=current['binding']['memory_id'], binding_source_ids=('new',))
        with self.assertRaisesRegex(CSMError, 'outside_journal'): self.session.publish(self.claim())

    def test_source_damage_cannot_publish_previously_bound_claim(self):
        self.fixture.store.db.execute('UPDATE events SET data=? WHERE id=?', ('{}', 'new'))
        with self.assertRaisesRegex(CSMError, 'digest_mismatch'): self.session.publish(self.claim())

    def test_empty_known_set_never_becomes_world_total_zero(self):
        self.core.ingest([Event('empty', 'chat', {'text':'No companions remain.'},
                                observed_at='2026-01-02T00:00:00Z')])
        journal=self.fixture.bridge.journal;current=journal.inspect(self.key)
        owner=current['binding']['owner_ref'];proof=SourceSpan('empty',('text',),'No companions remain.')
        binding=PropertyBinding(owner,contexts=self.fixture.bridge.contexts,
            memory_id=current['binding']['memory_id'],expected_revision=1,expected_value=self.refs,evidence=(proof,))
        candidate=MemoryCandidate(owner,self.fixture.spec.key,[],contexts=self.fixture.bridge.contexts,
            source_ids=('empty',),expected_revision=1,valid_from='2026-01-02T00:00:00Z')
        p=journal.propose(request_id='empty',spec_key=self.fixture.spec.key,binding=binding,candidate=candidate,
            operation='replace',coverage='source_claimed_complete',coverage_evidence=(proof,))
        journal.review(p['proposal_id'],expected_digest=p['digest'],decision='accepted',reviewer='offline-fixture',
                       reason='Source reports no remaining members; world completeness remains unverified.',evidence=(proof,))
        journal.commit(p['proposal_id'],expected_digest=p['digest'])
        session=SourceClaimSession(self.core,self.key)
        self.assertEqual(0,session.definition()['function']['parameters']['properties']['member_refs']['maxItems'])
        receipt=session.publish(self.claim(member_refs=[]))
        self.assertIsNone(receipt['world_total']);self.assertIn('offers no member entries',receipt['answer'])
        with self.assertRaisesRegex(CSMError,'world_total_not_established'):
            session.publish(self.claim(member_refs=[],world_total=0))

    def test_duplicate_keys_and_wrong_projection_are_rejected(self):
        duplicate = self.claim()[:-1] + ',"world_total":null}'
        with self.assertRaisesRegex(CSMError, 'duplicate_key'): self.session.publish(duplicate)
        with self.assertRaisesRegex(CSMError, 'projection_not_offered'):
            self.session.publish(self.claim(projection_ref='p2'))

    def test_native_free_prose_is_not_the_published_answer(self):
        receipt = self.session.publish_response(self.response())
        self.assertNotIn('exactly', receipt['answer']); self.assertEqual(['A', 'B'], receipt['member_labels'])
        with self.assertRaisesRegex(CSMError, 'tool_required'):
            self.session.publish_response(self.response(finish='stop'))
        with self.assertRaisesRegex(CSMError, 'tool_required'):
            self.session.publish_response(self.response(finish='length'))

    def test_native_unknown_tool_or_batch_is_not_executed(self):
        data = self.response(); data['choices'][0]['message']['tool_calls'][0]['function']['name'] = 'shell'
        with self.assertRaisesRegex(CSMError, 'not_offered'): self.session.publish_response(data)
        data = self.response(); data['choices'][0]['message']['tool_calls'] *= 2
        with self.assertRaisesRegex(CSMError, 'batch_invalid'): self.session.publish_response(data)

    def test_omitted_projection_does_not_publish_no_members_world_claim(self):
        session = SourceClaimSession(self.core, self.key, max_members=1)
        refs = [m['entity_ref'] for m in session.context()['members']]
        receipt = session.publish(self.claim(member_refs=refs))
        self.assertEqual(1, receipt['omitted_from_projection'])
        self.assertIn('Additional source members were omitted', receipt['answer'])

    def test_receipt_budget_rejects_whole_publication(self):
        session = SourceClaimSession(self.core, self.key, publication_chars=512)
        with self.assertRaisesRegex(CSMError, 'publication_budget'): session.publish(self.claim())

    def test_adapter_has_one_attempt_no_unvalidated_fallback(self):
        class Chat:
            calls = 0
            def exchange(inner, messages, **kwargs):
                inner.calls += 1
                self.assertEqual('auto', kwargs['tool_choice'])
                return self.response(arguments=self.claim(world_total=3))
        chat = Chat()
        with self.assertRaisesRegex(CSMError, 'world_total_not_established'):
            source_claim_answer.answer(chat, self.core, self.key, 'How many?', 'unchanged benchmark system')
        self.assertEqual(1, chat.calls)


if __name__ == '__main__': unittest.main()
