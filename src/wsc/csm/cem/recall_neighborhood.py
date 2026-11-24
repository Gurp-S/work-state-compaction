"""Bounded source neighborhoods. Text overlap establishes no identity."""
from .recall_scoring import overlap_weight


def dialogue_bounds(turns, index):
    turn = turns[index]
    following = turns[index + 1] if index + 1 < len(turns) else None
    if (isinstance(following, dict) and turn.get("speaker") and following.get("speaker")
            and turn["speaker"] != following["speaker"]
            and str(turn.get("text", "")).rstrip().endswith(("?", "？"))):
        return max(0, index - 1), index + 2
    return max(0, index - 1), index + 1


def prioritize_linked_observation(ranked, candidates, bags, frequency, base_scores):
    """Carry one related independent observation beside the strongest direct source."""
    standalone = [i for i in ranked if candidates[i].get("source_scope") == "observed_event"]
    if not standalone:
        return ranked
    seed = max(standalone, key=lambda i: base_scores[i])
    if base_scores[seed] <= 0:
        return ranked
    matches = []
    for index, candidate in enumerate(candidates):
        if index == seed or candidate.get("source_scope") != "observed_event":
            continue
        shared = {term for term in bags[seed] & bags[index]
                  if len(term) >= 2 and frequency[term] * 20 <= len(bags)}
        if len(shared) >= 2:
            matches.append((overlap_weight(shared, frequency, len(bags)), index))
    if not matches:
        return ranked
    _, linked = max(matches, key=lambda match: (match[0], -match[1]))
    ordered = [index for index in ranked if index != linked]
    ordered.insert(ordered.index(seed) + 1, linked)
    return ordered
