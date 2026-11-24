import unittest

from wsc.csm.cem.commitment_candidates import discover_commitment_candidates


class CommitmentCandidatesTest(unittest.TestCase):
    def test_offsets_and_ambiguity(self):
        text = '明天去看；本周三前交；周一到周五开放；已经完成另一件事。'
        candidates = discover_commitment_candidates('event/3', 'user', text, '2026-11-10T12:00:00+08:00')
        self.assertEqual([c.text for c in candidates], ['明天', '本周三前', '周一到周五', '已经完成'])
        self.assertEqual([text[c.start:c.end] for c in candidates], [c.text for c in candidates])
        self.assertEqual(candidates[0].day, ('2026-11-11T00:00:00+08:00', '2026-11-12T00:00:00+08:00'))
        self.assertEqual(candidates[1].kind, 'deadline_date')
        self.assertEqual(candidates[1].day, candidates[0].day)
        self.assertTrue(all(c.day is None for c in candidates[2:]))
        self.assertEqual(candidates[-1].kind, 'lifecycle_cue')
        self.assertEqual(discover_commitment_candidates('event/4', 'assistant', '天气不错。', ''), ())

    def test_negated_deadline_is_not_promoted(self):
        text = 'The parcel will arrive not before next Friday.'
        candidates = discover_commitment_candidates('event/5', 'user', text, '2026-11-10T12:00:00+08:00')
        self.assertEqual(['calendar'], [c.kind for c in candidates])
        self.assertIsNone(candidates[0].day)

    def test_month_end_requires_a_deadline_and_uses_source_month(self):
        stamp = '2028-01-07T12:00:00+08:00'
        candidates = discover_commitment_candidates('event/6', 'user', '月底前交，月底一起吃饭。', stamp)
        candidates += discover_commitment_candidates('event/7', 'user', '下月底前再确认。', stamp)
        self.assertEqual(['月底前', '月底', '下月底前'], [row.text for row in candidates])
        self.assertEqual(['2028-01-31T00:00:00+08:00', None, '2028-02-29T00:00:00+08:00'],
                         [row.day[0] if row.day else None for row in candidates])
