"""A reviewed commitment changes applicability without changing query wording."""
import unittest

from test_csm_source_inspection import MemoryStore
from wsc.csm import CSM, Event, MemoryCandidate
from wsc.csm.cem.calendar_anchors import resolve_calendar_day
from wsc.csm.cem.commitment_ingestion import CommitmentDraft, stage_commitment
from wsc.csm.cem.commitment_projection import PROPERTY_KEY, commitment_state_at, commitments_due, reviewed_commitments_from_sources
from wsc.csm.cem.entity_registry import EntityRegistry
from wsc.csm.cem.property_journal import PropertyJournal
from wsc.csm.cem.semantic_contract import PropertyBinding, PropertySpec, SourceSpan


class CommitmentProjectionTests(unittest.TestCase):
    def setUp(self):
        store = MemoryStore()
        self.addCleanup(store.db.close)
        self.core = CSM(store, clock=lambda: '2026-01-10T00:00:00Z')
        self.original = self.add_source('original', '2026-01-01', 'I will collect the signed forms on January 4.')
        registry = EntityRegistry(self.core)
        registry.initialize()
        self.owner = registry.create(request_id='owner', label='Participant', evidence=(self.original,))['ref']
        self.journal = PropertyJournal(self.core)
        self.journal.initialize()
        self.journal.register(PropertySpec(PROPERTY_KEY, 'single'), evidence=(self.original,))
        self.receipt = None

    def add_source(self, source_id, day, text):
        self.core.ingest([Event(source_id, 'chat', {'user': text}, observed_at=day + 'T08:00:00Z')])
        return SourceSpan(source_id, ('user',), text)

    def commit(self, source, effective, start, end, *, status='scheduled', condition='unconditional'):
        kwargs = {}
        if self.receipt:
            head = self.receipt['head']
            kwargs = {'memory_id': head['memory_id'], 'expected_revision': head['revision'],
                      'expected_value': head['value']}
        value = {'description': 'Collect the signed forms', 'status': status, 'condition': condition,
                 'due_start': start + 'T00:00:00Z', 'due_end': end + 'T00:00:00Z'}
        prop = self.journal.propose(request_id=source.event_id, spec_key=PROPERTY_KEY,
            binding=PropertyBinding(self.owner, contexts=('collection',), evidence=(source,), **kwargs),
            candidate=MemoryCandidate('participant', 'collection', value, source_ids=(source.event_id,),
                contexts=('collection',), valid_from=effective + 'T08:00:00Z',
                expected_revision=kwargs.get('expected_revision')),
            operation='replace' if self.receipt else 'create')
        self.journal.review(prop['proposal_id'], expected_digest=prop['digest'], decision='accepted',
                            reviewer='test', reason='Explicit source statement.', evidence=(source,))
        self.receipt = self.journal.commit(prop['proposal_id'], expected_digest=prop['digest'])

    def due(self, now, cutoff=None):
        return commitments_due(self.core, now=now + 'T12:00:00Z',
                               source_until=(cutoff or now) + 'T12:00:00Z')

    def bound_state(self, now, cutoff=None):
        return commitment_state_at(self.core, binding_key=self.receipt['binding']['binding_key'],
                                   now=now + 'T12:00:00Z', source_until=(cutoff or now) + 'T12:00:00Z')

    def test_reschedule_and_cancellation_respect_the_visible_prefix(self):
        self.commit(self.original, '2026-01-01', '2026-01-04', '2026-01-05')
        moved = self.add_source('move', '2026-01-02', 'Collect the forms January 6 instead.')
        self.commit(moved, '2026-01-02', '2026-01-06', '2026-01-07')
        cancel = self.add_source('cancel', '2026-01-06', 'Collection is cancelled.')
        self.commit(cancel, '2026-01-06', '2026-01-06', '2026-01-07', status='cancelled')
        self.assertEqual(1, self.due('2026-01-04', '2026-01-01')[0]['revision'])
        self.assertEqual([], self.due('2026-01-04'))
        self.assertEqual('BEFORE_NAMED_DATE', self.bound_state('2026-01-04')['applicability'])
        self.assertEqual(2, self.due('2026-01-06', '2026-01-05')[0]['revision'])
        self.assertEqual([], self.due('2026-01-06'))
        self.assertEqual('DUE', self.bound_state('2026-01-06', '2026-01-05')['applicability'])
        self.assertEqual('CANCELLED', self.bound_state('2026-01-06')['applicability'])
        def linked(clock, visible, anchors):
            return reviewed_commitments_from_sources(self.core, source_refs=anchors, now=clock,
                                                    source_until=clock, visible_source_ids=visible)

        retained = linked('2026-01-06T12:00:00Z', {'original', 'move'}, ['original'])
        self.assertEqual(retained[0]['revision'], 2)
        self.assertEqual(retained[0]['matched_source_refs'], ['original'])
        self.assertEqual([span['event_id'] for span in retained[0]['evidence']], ['move'])
        self.assertEqual(linked('2026-01-01T12:00:00Z', {'original'}, ['move']), [])

    def test_unresolved_condition_does_not_become_due(self):
        self.commit(self.original, '2026-01-01', '2026-01-04', '2026-01-05', condition='unknown')
        self.assertEqual([], self.due('2026-01-04'))
        self.assertEqual('CONDITION_UNRESOLVED', self.bound_state('2026-01-04')['applicability'])

    def test_status_only_revisions_keep_original_date_evidence(self):
        def stage(source, request_id, *, status='scheduled', expression=None, prior=None, condition='unconditional'):
            draft = CommitmentDraft(source, self.owner, 'rent', '到物业缴交房租', status, condition, expression,
                                    target_binding=prior['binding']['binding_key'] if prior else None,
                                    expected_revision=prior['head']['revision'] if prior else None,
                                    temporal_kind='deadline' if prior is None else None)
            proposal = stage_commitment(self.core, draft, request_id=request_id,
                                        source_until='2026-01-10T12:00:00Z')
            self.journal.review(proposal['proposal_id'], expected_digest=proposal['digest'], decision='accepted',
                                reviewer='test', reason='Reviewed the quoted change.', evidence=(source,))
            return self.journal.commit(proposal['proposal_id'], expected_digest=proposal['digest'])

        date = self.add_source('rent-date', '2026-01-01', '工作室这一季度房租九千六，本月10号前我得亲自去物业交。')
        initial = stage(date, 'rent-date', expression='本月10号前', condition='unknown')
        cleared = self.add_source('rent-condition', '2026-01-08', '物业确认可以办理了。')
        updated = stage(cleared, 'rent-condition', condition='satisfied', prior=initial)
        done = self.add_source('rent-paid', '2026-01-10', '工作室的房租已经交了。')
        self.receipt = stage(done, 'rent-paid', status='fulfilled', prior=updated)
        current = self.bound_state('2026-01-10')
        self.assertEqual('FULFILLED', current['applicability'])
        self.assertEqual({'rent-date', 'rent-paid'}, {span['event_id'] for span in current['evidence']})
        self.assertEqual('BEFORE_NAMED_DATE', self.bound_state('2026-01-09')['applicability'])
        without_date = commitment_state_at(
            self.core, binding_key=current['binding_key'], now='2026-01-10T12:00:00Z',
            source_until='2026-01-10T12:00:00Z', visible_source_ids={'original', 'rent-condition', 'rent-paid'})
        self.assertIsNone(without_date)

    def test_source_date_is_resolved_before_review_and_published_after_commit(self):
        source = self.add_source('relative', '2026-01-01', '资料后天到，到了我去拿。')
        draft = CommitmentDraft(source, self.owner, 'delivery', '领取资料', 'scheduled', 'unconditional', '后天')
        proposal = stage_commitment(self.core, draft, request_id='deliver', source_until='2026-01-01T12:00:00Z')
        self.assertEqual([], self.due('2026-01-03'))
        self.journal.review(proposal['proposal_id'], expected_digest=proposal['digest'], decision='accepted',
                            reviewer='test', reason='Reviewed the source commitment.', evidence=(source,))
        self.journal.commit(proposal['proposal_id'], expected_digest=proposal['digest'])
        self.assertEqual('2026-01-03T00:00:00+00:00', self.due('2026-01-03')[0]['commitment']['due_start'])
        self.assertEqual([], self.due('2026-01-04'))

    def test_partial_source_phrase_cannot_turn_deadline_into_appointment(self):
        source = self.add_source('deadline', '2026-01-01', '本月二十七号前交资料。')
        quote = SourceSpan(source.event_id, source.path, '本月二十七号')
        draft = CommitmentDraft(quote, self.owner, 'deadline', '交资料', 'scheduled', 'unconditional', '本月二十七号')
        result = stage_commitment(self.core, draft, request_id='deadline', source_until='2026-01-01T12:00:00Z')
        self.assertEqual('pending_date', result['status'])

    def test_separate_date_and_event_use_source_clock_and_require_both_sources(self):
        date = self.add_source('date', '2026-01-01', '改到后天。')
        event = self.add_source('event', '2026-01-02', '改期的是领取资料。')
        draft = CommitmentDraft(event, self.owner, 'delivery', '领取资料', 'scheduled',
                                'unconditional', '后天', date_source=date)
        with self.assertRaisesRegex(ValueError, 'property_source_outside_cutoff'):
            stage_commitment(self.core, draft, request_id='delivery', source_until='2026-01-01T12:00:00Z')
        prop = stage_commitment(self.core, draft, request_id='delivery', source_until='2026-01-02T12:00:00Z')
        self.journal.review(prop['proposal_id'], expected_digest=prop['digest'], decision='accepted',
                            reviewer='test', reason='Reviewed both statements.', evidence=(event, date))
        self.journal.commit(prop['proposal_id'], expected_digest=prop['digest'])
        self.assertEqual([], self.due('2026-01-03', '2026-01-01'))
        self.assertEqual([], self.due('2026-01-04'))
        result = self.due('2026-01-03')[0]
        self.assertEqual({'event', 'date'}, {s['event_id'] for s in result['evidence']})
        for absent in ('event', 'date'):
            visible = {'original', 'event', 'date'} - {absent}
            self.assertEqual([], commitments_due(
                self.core, now='2026-01-03T12:00:00Z', source_until='2026-01-03T12:00:00Z',
                visible_source_ids=visible))

    def test_local_calendar_crosses_year_and_week_boundaries(self):
        self.assertEqual(('2027-01-03T00:00:00+08:00', '2027-01-04T00:00:00+08:00'),
                         resolve_calendar_day('下个月三号', '2026-12-30T23:55:00+08:00'))
        self.assertEqual('2027-01-04T00:00:00+08:00',
                         resolve_calendar_day('下周一', '2027-01-03T23:55:00+08:00')[0])

    def test_visible_source_ids_disambiguate_turns_with_equal_timestamps(self):
        self.commit(self.original, '2026-01-01', '2026-01-04', '2026-01-05')
        cancel = self.add_source('same-clock', '2026-01-01', 'Collection is cancelled.')
        self.commit(cancel, '2026-01-01', '2026-01-04', '2026-01-05', status='cancelled')
        self.assertEqual([], self.due('2026-01-04'))
        due = commitments_due(self.core, now='2026-01-04T12:00:00Z',
                              source_until='2026-01-01T08:00:00Z', visible_source_ids={'original'})
        self.assertEqual(1, due[0]['revision'])
        self.assertEqual(['original'], due[0]['source_refs'])


if __name__ == '__main__':
    unittest.main()
