"""One bounded, literal source-context expansion; it asserts no identity or relation."""
from .recall_scoring import overlap_weight


def expand_scores(candidates, bags, frequency, base_scores):
    total = len(bags)
    direct = sorted((i for i, row in enumerate(candidates)
                    if row["record_type"] == "source_event" and base_scores[i] > 0),
                   key=lambda i: (-base_scores[i], candidates[i]["memory_id"]))
    # A weak incidental match must not start an unrelated expansion. Expand
    # only the strongest source lane (ties are bounded), never weaker seeds.
    seeds = [i for i in direct if base_scores[i] == base_scores[direct[0]]][:3] if direct else []
    boosts = {}
    for index, row in enumerate(candidates):
        if row["record_type"] != "source_event":
            continue
        best = None
        for seed in seeds:
            if set(row["source_refs"]) & set(candidates[seed]["source_refs"]):
                continue
            shared = {term for term in bags[index] & bags[seed]
                      if len(term) >= 2 and frequency[term] * 20 <= total}
            if len(shared) < 2:
                continue
            score = min(0.5 * base_scores[seed],
                        0.5 * overlap_weight(shared, frequency, total))
            if best is None or score > best[0]:
                best = (score, seed, shared)
        if best:
            boosts[index] = best[0]
            row["retrieval_via"] = {"reason": "literal_source_overlap",
                "source_refs": candidates[best[1]]["source_refs"], "terms": sorted(best[2])}
    return boosts
