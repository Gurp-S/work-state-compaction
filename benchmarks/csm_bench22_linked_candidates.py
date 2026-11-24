"""Discover user-source candidates through terms corroborated by two ranking lanes."""
from collections import defaultdict
from math import log

from bench22.systems import tokens


def linked_candidates(user_index, question, visible, lexical, semantic, *, limit=4):
    """Return a bounded candidate search outside the seed pools and its literal linkage terms."""
    if not 1 <= limit <= 8:
        raise ValueError('invalid_linked_candidate_limit')
    left = [index for index in lexical[:6] if index in visible]
    right = [index for index in semantic[:5] if index in visible]
    if not left or not right:
        return [], []
    query = set(tokens(question))
    seeds = set(lexical) | set(semantic)
    words = defaultdict(set)
    for index in set(left) | set(right):
        for term in user_index.docs[index]:
            if len(term) >= 2 and term not in query:
                words[term].add(index)
    weighted = []
    for term, sources in words.items():
        if len(sources) < 2 or not sources.intersection(left) or not sources.intersection(right):
            continue
        postings = [index for index, _ in user_index.post[term] if index in visible]
        # Very common dialogue fragments do not describe the case being linked.
        if not 2 < len(postings) <= max(6, len(visible) // 25):
            continue
        weighted.append((log(len(visible) / len(postings)), term, postings))
    weighted.sort(key=lambda row: (-row[0], row[1]))
    matched = defaultdict(list)
    for score, term, postings in weighted[:12]:
        for index in postings:
            if index not in seeds:
                matched[index].append((score, term))
    candidates = [(sum(score for score, _ in matches), index)
                  for index, matches in matched.items() if len(matches) >= 2]
    candidates.sort(key=lambda row: (-row[0], row[1]))
    best = [index for _, index in candidates[:limit]]
    return best, [{term for _, term in matched[index]} for index in best]
