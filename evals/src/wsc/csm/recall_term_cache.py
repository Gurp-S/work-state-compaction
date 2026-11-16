"""Bounded, content-keyed memoization of pure lexical normalization only.

No event, digest result, state, date, score, or retrieval packet is cached.
Every caller must still validate and construct its current source view.
"""
from functools import lru_cache

from .recall_terms import terms

MAX_ENTRIES = 2048
MAX_TEXT_CHARS = 4096


@lru_cache(maxsize=MAX_ENTRIES)
def _cached(text):
    return frozenset(terms(text))


def cached_terms(text):
    if len(text) > MAX_TEXT_CHARS:
        return frozenset(terms(text))
    return _cached(text)


def cache_info():
    return _cached.cache_info()


def clear_cache():
    _cached.cache_clear()
