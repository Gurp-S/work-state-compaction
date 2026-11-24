"""Cache equality, content invalidation and bounded retention without files."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wsc.csm import recall_term_cache as cache
from wsc.csm.cem.recall_terms import terms


class TermCache(unittest.TestCase):
    def setUp(self):
        cache.clear_cache()
        self.addCleanup(cache.clear_cache)

    def test_exact_text_keys_cannot_return_old_terms_after_source_changes(self):
        for text in ('住四楼 blue wall', '住五楼 wooden floor', '住四楼 blue wall'):
            self.assertEqual(cache.cached_terms(text), terms(text))
        self.assertEqual(cache.cache_info().hits, 1)
        self.assertIsInstance(cache.cached_terms('blue wall'), frozenset)

    def test_entry_count_and_long_input_bypass_are_bounded(self):
        text = 'x' * (cache.MAX_TEXT_CHARS + 1)
        self.assertEqual(cache.cached_terms(text), terms(text))
        self.assertEqual(cache.cache_info().currsize, 0)
        for i in range(cache.MAX_ENTRIES + 1):
            cache.cached_terms(str(i))
        self.assertEqual(cache.cache_info().currsize, cache.MAX_ENTRIES)


if __name__ == '__main__':
    unittest.main()
