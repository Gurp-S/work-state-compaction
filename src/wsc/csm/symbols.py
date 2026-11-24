"""Deterministic identifier keys: the second index, and the code-anchor query path.

These tokens are retrieval-index keys, never identity anchors. Splitting
``RequestTimeout`` or ``_handle_timeout`` into ``request``/``timeout`` lets a subject word,
or the code a caller is editing, reach a revision whose message does not contain it.
"""
from __future__ import annotations

import re
from collections import Counter

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+")

SKIP_PREFIX = ("+++", "---", "diff --git", "index ", "@@", "new file", "deleted file",
               "similarity ", "rename ", "Binary files", "old mode", "new mode", "\\ No newline")

# Language keywords and generic identifiers that would flood both indexes.
STOP = frozenset("""
self none true false null return import from class def func function async await yield
pass lambda print raise except finally while break continue else elif static const let var
public private protected interface extends implements struct impl enum match switch case
default throw catch try typeof instanceof sizeof typedef using namespace template typename
void int str bool float double long short char byte list dict tuple set len range main init
args kwargs value values data name names text string number object result results count
index key keys item items file files path paths config options params param request
response error errors message messages context state update get set add remove call make
user users type types source target content line lines test tests core utils setup docs
commit commits branch merge version versions default module modules package packages
""".split())

MIN_LEN, MAX_LEN = 4, 40
MAX_SYMBOLS = 40
MAX_WEIGHT = 3
ANCHOR_TERMS = 8


def split_identifier(name: str) -> list[str]:
    """snake_case and camelCase pieces, lowercased and filtered; never the whole identifier."""
    out = []
    for piece in name.split("_"):
        if not piece:
            continue
        parts = _CAMEL.findall(piece) if any(char.islower() for char in piece) else [piece]
        for part in parts:
            token = part.lower()
            if MIN_LEN <= len(token) <= MAX_LEN and token not in STOP and not token.isdigit():
                out.append(token)
    return out


def token_counts(patch_text: str) -> Counter:
    """Sub-tokens of identifiers on added/removed diff lines only."""
    counts: Counter = Counter()
    for line in patch_text.splitlines():
        if not line or line.startswith(SKIP_PREFIX):
            continue
        if line[0] not in "+-":
            continue
        for name in _IDENT.findall(line[1:]):
            for token in split_identifier(name):
                counts[token] += 1
    return counts


def select(counts: Counter, keep: set[str] | None = None,
           limit: int = MAX_SYMBOLS) -> list[str]:
    """Most frequent distinctive tokens, capped per token so one symbol cannot dominate."""
    chosen = Counter({token: min(MAX_WEIGHT, count) for token, count in counts.items()
                      if keep is None or token in keep})
    return [token for token, _ in chosen.most_common(limit)]


def document_frequency(token_sets) -> Counter:
    frequency: Counter = Counter()
    for tokens in token_sets:
        frequency.update(tokens)
    return frequency


def query_terms(code_text: str, *, limit: int = ANCHOR_TERMS) -> list[str]:
    """Anchor keys from arbitrary code or file text: same split, stoplist and length rules."""
    counts: Counter = Counter()
    for name in _IDENT.findall(str(code_text or "")):
        for token in split_identifier(name):
            counts[token] += 1
    return select(counts, limit=limit)


__all__ = ["split_identifier", "token_counts", "select", "document_frequency", "query_terms",
           "MAX_SYMBOLS", "ANCHOR_TERMS", "STOP"]
