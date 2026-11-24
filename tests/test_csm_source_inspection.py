"""Explicit source lookup contracts on real RAM SQLite, no model or files."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, CSMError


class MemoryStore(CsmStore):
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.row_factory = sqlite3.Row
        super().__init__(':memory:', namespace='inspection-test')

    @contextmanager
    def connect(self):
        yield self.db


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.addCleanup(self.store.db.close)
        self.core = CSM(self.store, clock=lambda: '2026-01-10T00:00:00Z')
        self.turn = {'dia_id': 'answer', 'speaker': 'Person',
            'text': 'Recently I had a setback. Last month I got hurt and paused pottery.',
            'img_url': ['https://example.test/original'], 'extension': {'keep': [1, 2]}}
        self.core.ingest([Event('session', 'chat', {'date': 'original date', 'outer': 'preserved',
            'turns': [{'dia_id': 'prior', 'speaker': 'Other', 'text': 'How was your week?'}, self.turn]},
            observed_at='2026-01-01T00:00:00Z')])
        self.value = 'Person had a setback recently.'
        self.id = self.core.remember([MemoryCandidate('Person', 'setback', self.value,
            source_ids=('session',))])[0]['memory_id']

    def inspect(self, **kwargs):
        return self.core.source_evidence(self.id, revision=1, expected_value=self.value, **kwargs)

    def test_selected_revision_reaches_full_original_detail_and_media_without_writes(self):
        before = self.store.db.total_changes
        packet = self.inspect()
        self.assertEqual(self.store.db.total_changes, before)
        self.assertEqual(packet['anchor'], {'memory_id': self.id, 'revision': 1})
        self.assertIn('got hurt', json.dumps(packet))
        item = packet['items'][0]
        self.assertIn(self.turn, item['value']['turns'])
        self.assertEqual(item['value']['outer'], 'preserved')
        self.assertFalse(item['confirmed'])
        self.assertEqual(item['classification'], 'UNKNOWN')

    def test_missing_revision_or_wrong_value_never_selects_a_new_head(self):
        for revision, value, error in ((2, self.value, 'revision_missing'), (1, 'different', 'value_mismatch')):
            with self.subTest(revision=revision), self.assertRaisesRegex(CSMError, error):
                self.core.source_evidence(self.id, revision=revision, expected_value=value)

    def test_historical_revision_remains_explicit_after_update(self):
        self.core.remember([MemoryCandidate('Person', 'setback', 'A different observation.',
            source_ids=('session',), intent='update')])
        self.assertIn('got hurt', json.dumps(self.inspect()))
        with self.assertRaisesRegex(CSMError, 'value_mismatch'):
            self.core.source_evidence(self.id, revision=2, expected_value=self.value)

    def test_source_integrity_is_rechecked_after_warm_lookup(self):
        self.inspect()
        with self.store.transaction() as db:
            db.execute('UPDATE events SET data=? WHERE id=?', ('{"text":"tampered"}', 'session'))
        with self.assertRaisesRegex(CSMError, 'digest_mismatch'):
            self.inspect()

    def test_missing_source_is_not_silently_replaced(self):
        with self.store.transaction() as db:
            db.execute('DELETE FROM events WHERE id=?', ('session',))
        with self.assertRaisesRegex(CSMError, 'source_missing'):
            self.inspect()

    def test_cutoff_rejects_revision_or_source_outside_scope(self):
        with self.assertRaisesRegex(CSMError, 'revision_outside_cutoff'):
            self.inspect(until='2025-12-31T00:00:00Z')
        self.assertTrue(self.inspect(until='2026-02-01T00:00:00Z')['items'])
        self.core.ingest([Event('future', 'chat', {'text': 'future source'},
            observed_at='2026-03-01T00:00:00Z')])
        value = 'future source'
        mid = self.core.remember([MemoryCandidate('Person', 'backdated', value,
            source_ids=('future',), valid_from='2026-01-01T00:00:00Z')])[0]['memory_id']
        with self.assertRaisesRegex(CSMError, 'source_outside_cutoff'):
            self.core.source_evidence(mid, revision=1, expected_value=value,
                                      until='2026-02-01T00:00:00Z')

    def test_final_serialized_budget_omits_whole_records(self):
        packet = self.inspect(max_chars=512)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))), 512)
        self.assertFalse(packet['items'])
        self.assertTrue(packet['truncated'])

    def test_unmatched_literal_context_stays_unknown(self):
        value = 'saffron compass exceptional'
        mid = self.core.remember([MemoryCandidate('Person', 'unmatched', value,
            source_ids=('session',))])[0]['memory_id']
        packet = self.core.source_evidence(mid, revision=1, expected_value=value)
        self.assertFalse(packet['items'])
        self.assertEqual(packet['context_binding'], 'not_established')

    def test_equal_windows_keep_question_and_reply_within_existing_budget(self):
        turns = [
            {'dia_id': '1', 'speaker': 'Person', 'text': 'I just got these shoes.',
             'img_url': ['https://example.test/' + 'a' * 650]},
            {'dia_id': '2', 'speaker': 'Other', 'text': 'For walking or jogging?'},
            {'dia_id': '3', 'speaker': 'Person', 'text': 'They are for jogging.'},
            {'dia_id': '4', 'speaker': 'Other', 'text': 'What got you into jogging?'},
            {'dia_id': '5', 'speaker': 'Person', 'text': 'I jog to prepare for a hike.'},
        ]
        self.core.ingest([Event('jogging', 'chat', {'turns': turns})])
        value = 'Other asked Person what got them into jogging.'
        mid = self.core.remember([MemoryCandidate('Person', 'jogging_question', value,
                                                  source_ids=('jogging',))])[0]['memory_id']
        packets = []
        for flag in ('0', '1'):
            with patch.dict(os.environ, {'WSC_CSM_SOURCE_FOCUS': flag}):
                packets.append(self.core.source_evidence(mid, revision=1, expected_value=value,
                                                        max_chars=1872))
        before, after = packets
        self.assertEqual(['1', '2', '3'], [t['dia_id'] for t in before['items'][0]['value']['turns']])
        self.assertEqual(turns[2:], after['items'][0]['value']['turns'])
        self.assertLessEqual(after['used_chars'], 1872)


if __name__ == '__main__':
    unittest.main()
