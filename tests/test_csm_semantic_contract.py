"""Read-only semantics planning on actual SQLite; old value operations reused."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.csm import CSM, CSMError, Event, MemoryCandidate
from wsc.csm.cem.semantic_contract import PropertySpec, PropertyBinding, RelationClaim, SourceSpan, plan
from test_csm_source_inspection import MemoryStore


class SemanticContractTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.addCleanup(self.store.db.close)
        self.core = CSM(self.store, clock=lambda: '2026-01-10T00:00:00Z')
        for event_id, text in [('base', 'Keeper has companions A and B.'),
                               ('add', 'Keeper has another companion C.'),
                               ('remove', 'Companion A left Keeper.'),
                               ('snapshot', 'The complete list of Keeper companions is B and C.')]:
            self.core.ingest([Event(event_id, 'chat', {'turns': [{'text': text, 'media': {'keep': True}}]},
                observed_at='2026-01-01T00:00:00Z')])
        self.refs = {name: 'node:' + self.core.create_node(name=name, node_type='entity',
                     entity_anchor=name, evidence=('base',))['node_id'] for name in ('Keeper', 'A', 'B', 'C')}
        self.spec = PropertySpec('registry:companions/v1', 'set', 'OWNED_BY', 'object')
        self.old = [self.refs['A'], self.refs['B']]
        self.mid = self.core.remember_explicit(MemoryCandidate('Keeper', 'companions', self.old,
            source_ids=('base',), valid_from='2026-01-01T00:00:00Z'), operation='create')['memory_id']
        self.binding = PropertyBinding(self.refs['Keeper'], memory_id=self.mid,
            expected_revision=1, expected_value=self.old,
            evidence=(self.span('base', 'Keeper has companions A and B.'),))
        self.candidate = MemoryCandidate('new surface', 'owner description', [self.refs['C']],
            source_ids=('add',), expected_revision=1, valid_from='2026-01-02T00:00:00Z')
        self.claim = RelationClaim('OWNED_BY', self.refs['C'], self.refs['Keeper'], 'assert',
                                  (self.span('add', 'Keeper has another companion C.'),))

    @staticmethod
    def span(event, quote): return SourceSpan(event, ('turns', 0, 'text'), quote)

    def preview(self, **kwargs):
        args = dict(operation='set_add', relations=(self.claim,))
        args.update(kwargs)
        return plan(self.core, self.spec, self.binding, self.candidate, **args)

    def test_valid_relation_plan_does_not_commit_or_confirm(self):
        before = self.store.db.total_changes
        result = self.preview()
        self.assertEqual(result['status'], 'structurally_valid')
        self.assertEqual(result['semantic_support'], 'not_verified')
        self.assertTrue(result['requires_semantic_review'])
        self.assertFalse(result['confirmed']); self.assertIsNone(result['world_total'])
        self.assertEqual(before, self.store.db.total_changes)
        self.assertEqual(self.old, self.core.memory(self.mid)['current']['value'])

    def test_existing_delta_executor_preserves_other_members_and_history(self):
        result = self.preview()
        self.core.remember_explicit(MemoryCandidate(**result['candidate']), operation=result['operation'],
            target_memory_id=self.mid, binding_source_ids=result['source_refs'])
        current = self.core.memory(self.mid)['current']
        self.assertEqual(self.old + [self.refs['C']], current['value'])
        self.binding = replace(self.binding, expected_revision=2, expected_value=current['value'])
        self.candidate = replace(self.candidate, value=[self.refs['A']], expected_revision=2,
                                 source_ids=('remove',), valid_from='2026-01-03T00:00:00Z')
        ended = replace(self.claim, subject=self.refs['A'], effect='end',
                        evidence=(self.span('remove', 'Companion A left Keeper.'),))
        result = self.preview(operation='set_remove', relations=(ended,))
        self.core.remember_explicit(MemoryCandidate(**result['candidate']), operation=result['operation'],
            target_memory_id=self.mid, binding_source_ids=result['source_refs'])
        self.assertEqual([self.refs['B'], self.refs['C']], self.core.memory(self.mid)['current']['value'])
        self.assertEqual(self.old, self.core.memory(self.mid, history=True)['history'][0]['value'])
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM relations').fetchone()[0])

    def test_missing_membership_or_binding_is_pending_not_a_guessed_edge(self):
        self.assertIn('member_relation_evidence', self.preview(relations=())['missing_conditions'])
        self.binding = replace(self.binding, evidence=())
        self.assertIn('owner_property_binding_evidence', self.preview()['missing_conditions'])

    def test_reversed_owner_or_wrong_member_cannot_bind(self):
        for wrong in (replace(self.claim, subject=self.refs['Keeper'], object=self.refs['C']),
                      replace(self.claim, subject=self.refs['B'])):
            with self.assertRaisesRegex(CSMError, 'member_mismatch'):
                self.preview(relations=(wrong,))

    def test_wrong_relation_effect_or_context_is_rejected(self):
        for claim, code in [(replace(self.claim, effect='end'), 'effect_mismatch'),
                            (replace(self.claim, contexts=('other occasion',)), 'context_mismatch')]:
            with self.assertRaisesRegex(CSMError, code): self.preview(relations=(claim,))

    def test_partial_snapshot_cannot_silently_remove_unmentioned_members(self):
        result = self.preview(operation='replace')
        self.assertEqual('pending_review', result['status'])
        self.assertIn('replacement_complete_snapshot_declaration', result['missing_conditions'])

    def test_complete_source_claim_needs_quote_and_never_proves_world_total(self):
        result = self.preview(operation='replace', coverage='source_claimed_complete')
        self.assertIn('complete_snapshot_evidence', result['missing_conditions'])
        result = self.preview(operation='replace', coverage='source_claimed_complete',
            coverage_evidence=(self.span('snapshot', 'The complete list of Keeper companions is B and C.'),))
        # C alone contradicts that quoted list: this is intentionally NOT a semantic validator.
        self.assertEqual('structurally_valid', result['status'])
        self.assertEqual('not_verified', result['semantic_support'])
        self.assertIsNone(result['world_total'])

    def test_quote_and_digest_checks_fail_without_fallback(self):
        with self.assertRaisesRegex(CSMError, 'quote_mismatch'):
            self.preview(relations=(replace(self.claim, evidence=(self.span('add', 'invented'),)),))
        self.store.db.execute('UPDATE events SET data=? WHERE id=?', ('{}', 'add'))
        with self.assertRaisesRegex(CSMError, 'digest_mismatch'): self.preview()

    def test_path_does_not_conflate_quote_from_another_field_or_accept_bool_index(self):
        for path in (('turns', 0, 'media'), ('turns', False, 'text')):
            claim = replace(self.claim, evidence=(replace(self.claim.evidence[0], path=path),))
            with self.assertRaises(CSMError): self.preview(relations=(claim,))

    def test_stale_version_or_wrong_base_is_rejected(self):
        for binding, candidate, code in [
            (replace(self.binding, expected_revision=2), replace(self.candidate, expected_revision=2), 'revision_conflict'),
            (replace(self.binding, expected_value=[]), self.candidate, 'base_value_mismatch')]:
            with self.assertRaisesRegex(CSMError, code):
                plan(self.core, self.spec, binding, candidate, operation='set_add', relations=(self.claim,))

    def test_old_string_list_is_not_automatically_converted_to_entity_members(self):
        self.store.db.execute('UPDATE revisions SET data=json_set(data,\'$.value\',json(?)) WHERE memory_id=?',
                              (json.dumps(['A', 'B']), self.mid))
        self.binding = replace(self.binding, expected_value=['A', 'B'])
        with self.assertRaisesRegex(CSMError, 'entity_ref_invalid'): self.preview()

    def test_time_missing_or_future_does_not_become_current(self):
        self.candidate = replace(self.candidate, valid_from=None)
        self.assertIn('effective_time', self.preview()['missing_conditions'])
        self.candidate = replace(self.candidate, valid_from='2025-12-01T00:00:00Z')
        with self.assertRaisesRegex(CSMError, 'historical_change'): self.preview()
        self.candidate = replace(self.candidate, valid_from='2026-02-01T00:00:00Z')
        with self.assertRaisesRegex(CSMError, 'effective_after_cutoff'):
            self.preview(until='2026-01-10T00:00:00Z')

    def test_delta_never_claims_complete_collection(self):
        with self.assertRaisesRegex(CSMError, 'delta_complete_claim'):
            self.preview(coverage='source_claimed_complete')

    def test_existing_domain_and_collection_lifecycle_rules_are_not_bypassed(self):
        self.candidate = replace(self.candidate, status='done')
        with self.assertRaisesRegex(CSMError, 'domain_status_unknown'): self.preview(relations=())
        self.candidate = replace(self.candidate, status=None, lifecycle='closed')
        with self.assertRaisesRegex(CSMError, 'collection_state_scope'): self.preview()

    def test_unquoted_base_source_is_still_integrity_checked(self):
        self.binding = replace(self.binding, evidence=self.claim.evidence)
        self.store.db.execute('UPDATE events SET data=? WHERE id=?', ('{}', 'base'))
        with self.assertRaisesRegex(CSMError, 'digest_mismatch'): self.preview()

    def test_single_value_and_observation_are_distinct_from_set_updates(self):
        single = PropertySpec('registry:colour/v1', 'single')
        with self.assertRaisesRegex(CSMError, 'single_delta_invalid'):
            plan(self.core, single, self.binding, self.candidate, operation='set_add')
        observation = PropertySpec('registry:observations/v1', 'observation')
        result = plan(self.core, observation, replace(self.binding, memory_id=None,
            expected_revision=None, expected_value=None),
            replace(self.candidate, expected_revision=None, value='An animal was observed.'), operation='observe')
        self.assertFalse(result['state_changed'])
        with self.assertRaisesRegex(CSMError, 'observation_state_operation'):
            plan(self.core, observation, self.binding, self.candidate, operation='replace')


if __name__ == '__main__': unittest.main()
