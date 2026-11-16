"""Rank visible current revisions by wording and flat identity anchors."""
from collections import Counter
from math import log

from wsc.csm.recall_terms import query_terms, terms


def rank_revisions(question, rows, *, limit=12, embedder=None, vector_cache=None):
    current = [row for row in rows if row['classification'] != 'HISTORICAL']
    anchors = [terms(' '.join((row['entity'], row['slot'], *row['contexts']))) for row in current]
    values = [terms(str(row['value'])) for row in current]
    bags = [anchor | value for anchor, value in zip(anchors, values)]
    wanted = query_terms(question, bags)
    frequencies = Counter(term for bag in bags for term in bag & wanted)
    weights = {term: (1 + log((len(current) + 1) / (count + 1))) *
               (0.2 if len(term) == 1 and not term.isascii() else 1)
               for term, count in frequencies.items()}
    named = {row['entity'] for row in current if len(row['entity']) >= 2 and row['entity'] in question}
    ranked = []
    for index, (row, anchor, bag) in enumerate(zip(current, anchors, bags)):
        matching = bag & wanted
        if not matching:
            continue
        subject = int(row['entity'] in named or any(name in row['contexts'] for name in named))
        score = sum(weights[term] * (1.3 if term in anchor else 1) for term in sorted(matching))
        ranked.append((-subject, -score, index, row))
    lexical = sorted(ranked)
    if embedder is None or not current:
        return [row for _, _, _, row in lexical[:limit]]
    docs = [' '.join((row['entity'], row['slot'], *row['contexts'], str(row['value']))) for row in current]
    if vector_cache is None:
        vectors = embedder.embed(docs)
    else:
        from numpy import stack

        missing = [doc for doc in dict.fromkeys(docs) if doc not in vector_cache]
        if missing:
            vector_cache.update(zip(missing, embedder.embed(missing), strict=True))
        vectors = stack([vector_cache[doc] for doc in docs])
    scores = vectors @ embedder.query(question)[0]
    dense = sorted(range(len(current)), key=lambda index: (-scores[index], index))
    # A semantic match can recover states with no shared literal words.
    fused = {index: 1 / (10 + rank) for rank, index in enumerate(dense)}
    for rank, (_, _, index, _) in enumerate(lexical):
        fused[index] += 0.35 / (10 + rank)
    return [current[index] for index in sorted(fused, key=lambda index: (-fused[index], index))[:limit]]
