"""Offline reallocation of ordinary evidence after state citations are fixed."""
from csm_bench22_passages import source_passage


def rebalance_long_evidence(question, *, existing, state_turns, ranked, read_original, render, allowance):
    """Preserve state sources and spend space recovered from ordinary long turns."""
    selected = dict(existing)
    for turn, block in existing.items():
        if turn not in state_turns and len(block) > 650:
            excerpt = render(source_passage(read_original(turn), question, limit=420))
            if len(excerpt) < len(block):
                selected[turn] = excerpt
    if selected == existing:
        return existing, []
    left = allowance - sum(len(block) + 2 for block in selected.values())
    added = []
    for turn in ranked:
        if turn in selected:
            continue
        block = render(read_original(turn))
        if len(block) + 2 > left:
            continue
        selected[turn] = block
        left -= len(block) + 2
        added.append(turn)
        if len(added) == 2:
            break
    return (selected, added) if added else (existing, [])
