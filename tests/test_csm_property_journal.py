"""Reviewed side path: real SQL transactions, provenance, CAS and membership history."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.contracts import digest
from wsc.csm import CSM, CsmStore, CSMError, Event, MemoryCandidate
from wsc.csm.cem.entity_registry import EntityRegistry
from wsc.csm.cem.property_journal import PropertyJournal, TABLES
from wsc.csm.cem.semantic_contract import SourceSpan, PropertySpec, PropertyBinding, RelationClaim
from test_csm_source_inspection import MemoryStore


class PropertyJournalTests(unittest.TestCase):
    def build(self, store):
        self.store = store
        self.core = CSM(store, clock=lambda: '2026-01-10T00:00:00Z')
        for event, text in [('base', 'Keeper has companions A and B.'), ('add', 'C joined Keeper.'),
                            ('remove', 'A left Keeper.'), ('full', 'The full list is B and C.'),
                            ('noop', 'Keeper still has companion A.')]:
            self.core.ingest([Event(event, 'chat', {'text': text}, observed_at='2026-01-01T00:00:00Z')])
        registry = EntityRegistry(self.core); registry.initialize()
        self.refs = {n: registry.create(request_id=n, label=n, evidence=(self.span('base'),))['ref']
                     for n in ('Keeper', 'A', 'B', 'C')}
        self.spec = PropertySpec('test:companions/v1', 'set', 'OWNED_BY', 'object')
        self.journal = PropertyJournal(self.core); self.journal.initialize()
        self.journal.register(self.spec, evidence=(self.span('base'),))
        self.counter = 0
        self.key = None

    def setUp(self):
        store = MemoryStore(); self.addCleanup(store.db.close); self.build(store)

    def span(self, event):
        with self.core.store.connect() as db:
            value = json.loads(db.execute('SELECT data FROM events WHERE id=?', (event,)).fetchone()[0])
        return SourceSpan(event, ('text',), value['text'])

    def propose(self, operation='create', members=('A', 'B'), event='base', *, request_id=None,
                coverage='partial', candidate_changes=None):
        self.counter += 1
        if operation == 'create':
            binding = PropertyBinding(self.refs['Keeper'], evidence=(self.span(event),))
            revision = None
        else:
            current = self.journal.inspect(self.key)
            binding = PropertyBinding(self.refs['Keeper'], memory_id=current['binding']['memory_id'],
                expected_revision=current['head']['revision'], expected_value=current['head']['value'],
                evidence=(self.span(event),))
            revision = current['head']['revision']
        candidate = MemoryCandidate('mutable display', 'mutable attribute label', [self.refs[m] for m in members],
            source_ids=(event,), expected_revision=revision,
            valid_from='2026-01-01T00:00:00Z' if operation == 'create' else '2026-01-02T00:00:00Z')
        if candidate_changes: candidate = replace(candidate, **candidate_changes)
        claims = tuple(RelationClaim('OWNED_BY', self.refs[m], self.refs['Keeper'],
            'end' if operation == 'set_remove' else 'assert', (self.span(event),)) for m in members)
        return self.journal.propose(request_id=request_id or str(self.counter), spec_key=self.spec.key,
            binding=binding, candidate=candidate, operation=operation, relations=claims,
            coverage=coverage, coverage_evidence=(self.span(event),) if coverage != 'partial' else ())

    def accept(self, proposal, event='base', decision='accepted'):
        return self.journal.review(proposal['proposal_id'], expected_digest=proposal['digest'],
            decision=decision, reviewer='offline-declared-fixture', reason='Explicit fixture role review.',
            evidence=(self.span(event),))

    def commit(self, proposal):
        result = self.journal.commit(proposal['proposal_id'], expected_digest=proposal['digest'])
        self.key = result['binding']['binding_key']; return result

    def create(self):
        p = self.propose(); self.accept(p); return self.commit(p)

    def snapshot(self):
        with self.core.store.connect() as db:
            return {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t + ' ORDER BY rowid')]
                for t in ('identities', 'revisions', 'heads', 'projection', 'identity_changes', *TABLES)}

    def test_initialization_is_explicit(self):
        store = MemoryStore(); self.addCleanup(store.db.close)
        core = CSM(store); journal = PropertyJournal(core)
        with self.assertRaisesRegex(CSMError, 'entity_registry_not_initialized'): journal.initialize()
        names = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(names.intersection(TABLES))

    def test_create_pins_stable_binding_and_keeps_world_unknown(self):
        result = self.create(); current = self.journal.inspect(self.key)
        self.assertEqual(self.refs['Keeper'], self.core.memory(result['binding']['memory_id'])['identity']['entity'])
        self.assertEqual({self.refs['A'], self.refs['B']}, set(current['active_members']))
        self.assertFalse(current['confirmed']); self.assertIsNone(current['world_total'])
        self.assertEqual('not_verified', result['semantic_support'])

    def test_add_remove_and_source_history_are_committed_together(self):
        initial = self.create()
        p = self.propose('set_add', ('C',), 'add',
                         candidate_changes={'entity': 'different display phrase', 'slot': 'different surface slot'})
        self.accept(p, 'add'); self.commit(p)
        p = self.propose('set_remove', ('A',), 'remove'); self.accept(p, 'remove'); self.commit(p)
        current = self.journal.inspect(self.key)
        self.assertEqual([self.refs['B'], self.refs['C']], current['head']['value'])
        self.assertEqual(set(current['head']['value']), set(current['active_members']))
        history = self.core.memory(initial['binding']['memory_id'], history=True)['history']
        self.assertEqual(3, len(history)); self.assertEqual([self.refs['A'], self.refs['B']], history[0]['value'])

    def test_review_and_exact_digest_are_required(self):
        p = self.propose(); before = self.snapshot()
        with self.assertRaisesRegex(CSMError, 'review_missing'): self.commit(p)
        self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(CSMError, 'digest_mismatch'):
            self.journal.review(p['proposal_id'], expected_digest='wrong', decision='accepted', reviewer='x',
                                reason='x', evidence=(self.span('base'),))
        self.accept(p, decision='rejected')
        with self.assertRaisesRegex(CSMError, 'not_accepted'): self.commit(p)

    def test_incomplete_replacement_cannot_be_accepted_or_written(self):
        self.create(); p = self.propose('replace', ('C',), 'add')
        self.assertEqual('pending_review', p['plan']['status'])
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, 'incomplete'): self.accept(p, 'add')
        self.assertEqual(before, self.snapshot())

    def test_complete_snapshot_ends_omitted_members_with_explicit_derivation(self):
        self.create(); p = self.propose('replace', ('B', 'C'), 'full', coverage='source_claimed_complete')
        self.accept(p, 'full'); self.commit(p)
        current = self.journal.inspect(self.key)
        self.assertEqual({self.refs['B'], self.refs['C']}, set(current['active_members']))
        with self.core.store.connect() as db:
            events = [json.loads(r[0]) for r in db.execute('SELECT data FROM csm_property_relation_events WHERE member_ref=?',
                                                          (self.refs['A'],))]
        self.assertEqual('caller_complete_snapshot_exclusion', events[-1]['derivation'])
        self.assertEqual('end', events[-1]['effect'])

    def test_complete_empty_snapshot_ends_all_known_members(self):
        self.create()
        self.core.ingest([Event('empty', 'chat', {'text': 'No companions remain.'},
                                observed_at='2026-01-01T00:00:00Z')])
        p = self.propose('replace', (), 'empty', coverage='source_claimed_complete')
        self.accept(p, 'empty'); self.commit(p)
        result = self.journal.inspect(self.key)
        self.assertEqual([], result['head']['value']); self.assertEqual({}, result['active_members'])
        self.assertIsNone(result['world_total'])

    def test_single_attribute_replacement_has_no_membership_side_effect(self):
        spec = PropertySpec('test:colour/v1', 'single')
        for event, text in [('colour', 'The object colour is blue.'), ('recolour', 'The same object is now green.')]:
            self.core.ingest([Event(event, 'chat', {'text': text}, observed_at='2026-01-01T00:00:00Z')])
        self.journal.register(spec, evidence=(self.span('colour'),))
        binding = PropertyBinding(self.refs['Keeper'], evidence=(self.span('colour'),))
        candidate = MemoryCandidate('object', 'colour', 'blue', source_ids=('colour',),
                                     valid_from='2026-01-01T00:00:00Z')
        p = self.journal.propose(request_id='blue', spec_key=spec.key, binding=binding,
                                 candidate=candidate, operation='create')
        self.accept(p, 'colour'); result = self.commit(p)
        binding = replace(binding, memory_id=result['binding']['memory_id'], expected_revision=1,
                           expected_value='blue', evidence=(self.span('recolour'),))
        candidate = replace(candidate, value='green', expected_revision=1, source_ids=('recolour',),
                             valid_from='2026-01-02T00:00:00Z')
        p = self.journal.propose(request_id='green', spec_key=spec.key, binding=binding,
                                 candidate=candidate, operation='replace')
        self.accept(p, 'recolour'); self.commit(p)
        current = self.journal.inspect(self.key)
        self.assertEqual('green', current['head']['value']); self.assertEqual({}, current['active_members'])

    def test_stale_accepted_proposal_cannot_overwrite_new_state(self):
        self.create(); stale = self.propose('set_add', ('C',), 'add'); self.accept(stale, 'add')
        other = self.propose('set_remove', ('A',), 'remove'); self.accept(other, 'remove'); self.commit(other)
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, 'revision_conflict'): self.commit(stale)
        self.assertEqual(before, self.snapshot())

    def test_changed_source_and_current_digest_cannot_reuse_accepted_review(self):
        self.create(); p = self.propose('set_add', ('C',), 'add'); self.accept(p, 'add')
        value = {'text': 'C joined Keeper.', 'extra': 'changed'}
        self.store.db.execute('UPDATE events SET data=?,digest=? WHERE id=?', (json.dumps(value), digest(value), 'add'))
        before = self.snapshot()
        with self.assertRaisesRegex(CSMError, 'source_changed'): self.commit(p)
        self.assertEqual(before, self.snapshot())

    def test_relation_failure_rolls_back_state_receipt_and_can_retry(self):
        self.create(); p = self.propose('set_add', ('C',), 'add'); self.accept(p, 'add')
        self.store.db.execute("CREATE TRIGGER fail_relation BEFORE INSERT ON csm_property_relation_events "
                              "BEGIN SELECT RAISE(ABORT, 'injected relation failure'); END")
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected relation failure'): self.commit(p)
        self.assertEqual(before, self.snapshot())
        self.store.db.execute('DROP TRIGGER fail_relation')
        self.commit(p); self.assertIn(self.refs['C'], self.journal.inspect(self.key)['head']['value'])

    def test_late_commit_failure_also_rolls_back_initial_binding(self):
        p = self.propose(); self.accept(p)
        self.store.db.execute("CREATE TRIGGER fail_commit BEFORE INSERT ON csm_property_commits "
                              "BEGIN SELECT RAISE(ABORT, 'injected final failure'); END")
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected final failure'): self.commit(p)
        self.assertEqual(before, self.snapshot())

    def test_direct_legacy_write_is_detected_not_silently_reconciled(self):
        initial = self.create()
        self.core.remember_explicit(MemoryCandidate('x', 'x', [self.refs['C']], source_ids=('add',), expected_revision=1),
            operation='replace', target_memory_id=initial['binding']['memory_id'], binding_source_ids=('add',))
        with self.assertRaisesRegex(CSMError, 'outside_journal'): self.journal.inspect(self.key)

    def test_external_identity_rekey_is_detected_even_if_head_did_not_change(self):
        initial = self.create()
        self.core.rekey(initial['binding']['memory_id'], contexts=('other scope',), evidence=('base',))
        with self.assertRaisesRegex(CSMError, 'identity_outside_journal'): self.journal.inspect(self.key)

    def test_commit_and_request_replay_do_not_duplicate_membership_events(self):
        p = self.propose(request_id='same'); self.accept(p); first = self.commit(p)
        before = self.snapshot(); repeated = self.commit(p)
        self.assertFalse(repeated['changed']); self.assertEqual(before, self.snapshot())
        other = self.propose('set_add', ('C',), 'add'); self.accept(other, 'add'); self.commit(other)
        old = self.commit(p)
        self.assertEqual(first['head']['revision'], old['head']['revision'])
        self.assertEqual(2, self.journal.inspect(self.key)['head']['revision'])

    def test_property_schema_cannot_change_under_same_key(self):
        with self.assertRaisesRegex(CSMError, 'spec_conflict'):
            self.journal.register(PropertySpec(self.spec.key, 'single'), evidence=(self.span('base'),))

    def test_review_cannot_sneak_in_another_source(self):
        p = self.propose()
        with self.assertRaisesRegex(CSMError, 'outside_proposal'): self.accept(p, 'full')

    def test_noop_provenance_remains_checked_after_later_commit(self):
        self.create()
        p = self.propose('set_add', ('A',), 'noop'); self.accept(p, 'noop'); noop = self.commit(p)
        self.assertFalse(noop['result']['changed'])
        p = self.propose('set_add', ('C',), 'add'); self.accept(p, 'add'); self.commit(p)
        value = {'text': 'Keeper still has companion A.', 'extra': 'changed'}
        self.store.db.execute('UPDATE events SET data=?,digest=? WHERE id=?', (json.dumps(value), digest(value), 'noop'))
        with self.assertRaisesRegex(CSMError, 'source_changed'): self.journal.inspect(self.key)

    def test_existing_old_memory_cannot_be_adopted_implicitly(self):
        mid = self.core.remember([MemoryCandidate('old', 'list', [self.refs['A']], source_ids=('base',),
            valid_from='2026-01-01T00:00:00Z')])[0]['memory_id']
        binding = PropertyBinding(self.refs['Keeper'], memory_id=mid, expected_revision=1,
            expected_value=[self.refs['A']], evidence=(self.span('add'),))
        candidate = MemoryCandidate('new', 'new', [self.refs['C']], source_ids=('add',), expected_revision=1,
            valid_from='2026-01-02T00:00:00Z')
        claim = RelationClaim('OWNED_BY', self.refs['C'], self.refs['Keeper'], 'assert', (self.span('add'),))
        with self.assertRaisesRegex(CSMError, 'binding_unregistered'):
            self.journal.propose(request_id='adopt', spec_key=self.spec.key, binding=binding,
                candidate=candidate, operation='set_add', relations=(claim,))

    def test_reopen_and_two_concurrent_accepted_writes_preserve_cas(self):
        with tempfile.TemporaryDirectory(prefix='csm-property-journal-') as folder:
            path = Path(folder) / 'memory.db'
            case = PropertyJournalTests(); case.build(CsmStore(path, namespace='journal'))
            case.create()
            a = case.propose('set_add', ('C',), 'add'); case.accept(a, 'add')
            b = case.propose('set_remove', ('A',), 'remove'); case.accept(b, 'remove')
            def commit(p):
                journal = PropertyJournal(CSM(CsmStore(path, namespace='journal')))
                try: journal.commit(p['proposal_id'], expected_digest=p['digest']); return 'committed'
                except CSMError as error: return str(error)
            with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(commit, (a, b)))
            self.assertEqual(1, results.count('committed'))
            self.assertTrue(any('revision_conflict' in r for r in results))
            current = PropertyJournal(CSM(CsmStore(path, namespace='journal'))).inspect(case.key)
            self.assertEqual(set(current['head']['value']), set(current['active_members']))

    def test_inspection_keeps_one_snapshot_during_a_concurrent_commit(self):
        with tempfile.TemporaryDirectory(prefix='csm-property-reader-') as folder:
            path = Path(folder) / 'memory.db'
            case = PropertyJournalTests(); case.build(CsmStore(path, namespace='reader'))
            with case.core.store.connect() as db: db.execute('PRAGMA journal_mode=WAL')
            case.create()
            p = case.propose('set_add', ('C',), 'add'); case.accept(p, 'add')
            original_active = PropertyJournal._active
            def hook(db, key):
                writer = PropertyJournal(CSM(CsmStore(path, namespace='reader')))
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(writer.commit, p['proposal_id'], expected_digest=p['digest'])
                    future.result(timeout=10)
                return original_active(db, key)
            with patch.object(case.journal, '_active', side_effect=hook):
                old = case.journal.inspect(case.key)
            self.assertEqual(2, len(old['head']['value']))
            self.assertEqual(set(old['head']['value']), set(old['active_members']))
            self.assertEqual(3, len(case.journal.inspect(case.key)['head']['value']))


if __name__ == '__main__': unittest.main()
