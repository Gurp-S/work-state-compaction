"""Explicit independent IDs: identity, provenance, index lifecycle and persistence."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.contracts import digest
from wsc.csm import CSM, CsmStore, CSMError, Event, MemoryCandidate
from wsc.csm.cem.entity_registry import EntityRegistry, TABLE_NAMES
from wsc.csm.cem.semantic_contract import SourceSpan, PropertySpec, PropertyBinding, RelationClaim, plan
from test_csm_source_inspection import MemoryStore


class EntityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.addCleanup(self.store.db.close)
        self.core = CSM(self.store, clock=lambda: '2026-01-10T00:00:00Z')
        self.core.ingest([Event('source', 'chat', {'text': 'Keeper has objects A and B. C joined Keeper. New label.'},
                                observed_at='2026-01-01T00:00:00Z')])
        self.evidence = (SourceSpan('source', ('text',), 'Keeper has objects A and B.'),)
        self.registry = EntityRegistry(self.core)

    def create(self, request='one', label='Same label'):
        self.registry.initialize()
        return self.registry.create(request_id=request, label=label, evidence=self.evidence)

    def node(self, name):
        return self.core.create_node(name=name, node_type='entity', entity_anchor=name,
                                     evidence=('source',))['node_id']

    def test_initialization_is_explicit_and_default_store_has_no_registry_tables(self):
        before = self.store.db.total_changes
        with self.assertRaisesRegex(CSMError, 'not_initialized'):
            self.registry.create(request_id='r', label='A', evidence=self.evidence)
        names = {r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(set(TABLE_NAMES) & names)
        self.assertEqual(before, self.store.db.total_changes)
        self.assertTrue(self.registry.initialize()['changed'])
        self.assertFalse(self.registry.initialize()['changed'])

    def test_same_name_is_not_equivalence_or_an_automatic_node_alias(self):
        a = self.create(); b = self.create('two', ' same LABEL ')
        self.assertNotEqual(a['ref'], b['ref'])
        result = self.registry.find_label('Same label')
        self.assertEqual('ambiguous', result['resolution'])
        self.assertEqual(2, len(result['matches']))
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM entity_aliases').fetchone()[0])
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM csm_entity_nodes').fetchone()[0])

    def test_creation_request_is_idempotent_even_after_rename(self):
        a = self.create()
        self.registry.set_label(a['ref'], label='New label', expected_revision=1, evidence=self.evidence)
        repeated = self.create()
        self.assertEqual(a['ref'], repeated['ref']); self.assertFalse(repeated['changed'])
        current = self.registry.get(a['ref'], history=True)
        self.assertEqual(['Same label', 'New label'], [r['label'] for r in current['label_history']])
        self.assertEqual('New label', current['current_label']['label'])
        with self.assertRaisesRegex(CSMError, 'request_conflict'): self.create(label='Another object')

    def test_label_cas_and_source_failure_do_not_append_history(self):
        a = self.create()
        with self.assertRaisesRegex(CSMError, 'revision_conflict'):
            self.registry.set_label(a['ref'], label='New', expected_revision=2, evidence=self.evidence)
        with self.assertRaisesRegex(CSMError, 'quote_mismatch'):
            self.registry.set_label(a['ref'], label='New', expected_revision=1,
                                    evidence=(SourceSpan('source', ('text',), 'invented'),))
        self.assertEqual(1, len(self.registry.get(a['ref'], history=True)['label_history']))

    def test_binding_is_explicit_versioned_and_not_a_merge(self):
        a = self.create(); b = self.create('two'); node = self.node('Index')
        with self.assertRaisesRegex(CSMError, 'unbound'): self.registry.resolve_node(node)
        self.registry.bind_node(a['ref'], node_id=node, evidence=self.evidence)
        with self.assertRaisesRegex(CSMError, 'binding_exists'):
            self.registry.bind_node(b['ref'], node_id=node, evidence=self.evidence, expected_revision=1)
        self.registry.unbind_node(a['ref'], node_id=node, evidence=self.evidence, expected_revision=1)
        self.registry.bind_node(b['ref'], node_id=node, evidence=self.evidence, expected_revision=2)
        self.assertEqual(b['entity_id'], self.registry.resolve_node(node)['entity_id'])
        self.assertEqual([True, False, True], [r['active'] for r in self.registry.node_history(node)])
        self.assertEqual(a['ref'], self.registry.get(a['ref'])['ref'])

    def test_retired_index_does_not_retire_entity_and_release_is_still_possible(self):
        a = self.create(); node = self.node('Old index')
        self.registry.bind_node(a['ref'], node_id=node, evidence=self.evidence)
        self.core.retire_node(node, evidence=('source',))
        self.assertEqual(a['ref'], self.registry.get(a['ref'])['ref'])
        with self.assertRaisesRegex(CSMError, 'unavailable'): self.registry.resolve_node(node)
        self.registry.unbind_node(a['ref'], node_id=node, evidence=self.evidence, expected_revision=1)
        new = self.node('New index')
        self.registry.bind_node(a['ref'], node_id=new, evidence=self.evidence)
        self.assertEqual(a['entity_id'], self.registry.resolve_node(new)['entity_id'])

    def test_tree_merge_does_not_merge_registered_objects(self):
        a = self.create('a', 'A'); b = self.create('b', 'B')
        na, nb = self.node('Index A'), self.node('Index B')
        self.registry.bind_node(a['ref'], node_id=na, evidence=self.evidence)
        self.registry.bind_node(b['ref'], node_id=nb, evidence=self.evidence)
        self.core.merge_nodes(na, nb, evidence=('source',))
        self.assertEqual(a['ref'], self.registry.get(a['ref'])['ref'])
        self.assertEqual(b['entity_id'], self.registry.resolve_node(nb)['entity_id'])
        with self.assertRaisesRegex(CSMError, 'unavailable'): self.registry.resolve_node(na)

    def test_missing_provenance_and_changed_source_seal_are_rejected(self):
        self.registry.initialize()
        with self.assertRaisesRegex(CSMError, 'evidence_missing'):
            self.registry.create(request_id='a', label='A', evidence=())
        a = self.create()
        payload = {'text': 'Keeper has objects A and B. C joined Keeper. New label.', 'other': 'changed'}
        self.store.db.execute('UPDATE events SET data=?,digest=? WHERE id=?',
                              (json.dumps(payload), digest(payload), 'source'))
        with self.assertRaisesRegex(CSMError, 'seal_mismatch'): self.registry.get(a['ref'])

    def test_partial_registry_format_is_not_silently_repaired(self):
        self.store.db.execute('CREATE TABLE csm_entities (id TEXT)')
        with self.assertRaisesRegex(CSMError, 'format_invalid'): self.registry.initialize()

    def test_entity_and_initial_label_commit_or_rollback_together(self):
        self.registry.initialize()
        self.store.db.execute("CREATE TRIGGER fail_label BEFORE INSERT ON csm_entity_labels "
                              "BEGIN SELECT RAISE(ABORT, 'injected label failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected label failure'):
            self.registry.create(request_id='failed', label='A', evidence=self.evidence)
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM csm_entities').fetchone()[0])
        self.assertEqual(0, self.store.db.execute('SELECT count(*) FROM csm_entity_labels').fetchone()[0])
        self.store.db.execute('DROP TRIGGER fail_label')
        self.assertTrue(self.registry.create(request_id='failed', label='A', evidence=self.evidence)['changed'])

    def make_plan(self):
        refs = {name: self.create(name, name)['ref'] for name in ('Keeper', 'A', 'B', 'C')}
        old = [refs['A'], refs['B']]
        mid = self.core.remember_explicit(MemoryCandidate('Old label', 'objects', old,
            source_ids=('source',), valid_from='2026-01-01T00:00:00Z'), operation='create')['memory_id']
        spec = PropertySpec('registry:objects/v1', 'set', 'OWNED_BY', 'object')
        binding = PropertyBinding(refs['Keeper'], memory_id=mid, expected_revision=1,
                                  expected_value=old, evidence=self.evidence)
        candidate = MemoryCandidate('C label', 'owner', [refs['C']], source_ids=('source',),
                                    expected_revision=1, valid_from='2026-01-02T00:00:00Z')
        claim = RelationClaim('OWNED_BY', refs['C'], refs['Keeper'], 'assert',
                              (SourceSpan('source', ('text',), 'C joined Keeper.'),))
        return refs, spec, binding, candidate, claim

    def test_collection_uses_independent_ids_through_rename_and_index_retirement(self):
        refs, spec, binding, candidate, claim = self.make_plan()
        def preview():
            return plan(self.core, spec, binding, candidate, operation='set_add',
                        relations=(claim,), entity_ids=True)
        first = preview()
        self.assertEqual('structurally_valid', first['status'])
        node = self.node('Old owner index')
        self.registry.bind_node(refs['Keeper'], node_id=node, evidence=self.evidence)
        self.registry.set_label(refs['Keeper'], label='Renamed', expected_revision=1, evidence=self.evidence)
        self.core.retire_node(node, evidence=('source',))
        last = preview()
        self.assertEqual(first['binding_key'], last['binding_key'])
        self.assertEqual(first['candidate']['value'], last['candidate']['value'])
        self.core.remember_explicit(candidate, operation='set_add', target_memory_id=binding.memory_id,
                                   binding_source_ids=last['source_refs'])
        self.core.rebuild()
        self.assertEqual([refs['A'], refs['B'], refs['C']], self.core.memory(binding.memory_id)['current']['value'])
        self.assertEqual(refs['Keeper'], self.registry.get(refs['Keeper'])['ref'])
        self.assertIsNone(last['world_total']); self.assertFalse(last['confirmed'])

    def test_entity_mode_cannot_fall_back_to_tree_or_name(self):
        refs, spec, binding, candidate, claim = self.make_plan()
        for wrong in ('node:' + self.node('Name'), 'Keeper'):
            with self.assertRaisesRegex(CSMError, 'entity_ref_invalid'):
                plan(self.core, spec, replace(binding, owner_ref=wrong), candidate, operation='set_add',
                     relations=(claim,), entity_ids=True)

    def test_identity_source_after_cutoff_is_not_used_in_earlier_plan(self):
        refs, spec, binding, candidate, claim = self.make_plan()
        with self.assertRaisesRegex(CSMError, 'source_outside_cutoff'):
            plan(self.core, spec, binding, candidate, operation='set_add', relations=(claim,),
                 entity_ids=True, until='2025-12-01T00:00:00Z')


class RegistryPersistenceTests(unittest.TestCase):
    def test_reopen_and_concurrent_same_request_keep_one_id(self):
        with tempfile.TemporaryDirectory(prefix='csm-entity-registry-') as folder:
            path = Path(folder) / 'memory.db'
            def core(): return CSM(CsmStore(path, namespace='registry-test'))
            first = core(); first.ingest([Event('e', 'chat', {'text': 'An object called X.'})])
            registry = EntityRegistry(first); registry.initialize()
            evidence = (SourceSpan('e', ('text',), 'An object called X.'),)
            def create(_):
                return EntityRegistry(core()).create(request_id='same-request', label='X', evidence=evidence)
            with ThreadPoolExecutor(max_workers=2) as pool: created = list(pool.map(create, range(2)))
            self.assertEqual(created[0]['ref'], created[1]['ref'])
            self.assertEqual(1, sum(row['changed'] for row in created))
            ref = created[0]['ref']
            registry.set_label(ref, label='Y', expected_revision=1, evidence=evidence)
            reloaded = EntityRegistry(core()).get(ref, history=True)
            self.assertEqual(['X', 'Y'], [r['label'] for r in reloaded['label_history']])
            with self.assertRaisesRegex(CSMError, 'namespace_conflict'):
                CsmStore(path, namespace='different')


if __name__ == '__main__': unittest.main()
