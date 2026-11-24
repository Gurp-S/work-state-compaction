"""Offline evidence ordering that fits complete turns around fixed state sources."""


def fit_whole_turns(question, *, existing, state_turns, ranked, read_original, render, allowance):
    """Give state sources and the newest retained turn first claim on space."""
    if not existing:
        return existing, []
    pinned = state_turns | {max(existing)}
    selected = {turn: block for turn, block in existing.items() if turn in pinned}
    remaining = allowance - sum(len(block) + 2 for block in selected.values())
    for turn in dict.fromkeys([*ranked, *reversed(existing)]):
        if turn in selected:
            continue
        block = existing.get(turn)
        if block is None:
            block = render(read_original(turn))
        cost = len(block) + 2
        if cost <= remaining:
            selected[turn] = block
            remaining -= cost
    return selected, sorted(selected.keys() - existing.keys())
