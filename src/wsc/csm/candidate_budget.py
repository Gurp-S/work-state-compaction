"""Bounded selection across direct hits and evidence-backed expansion.

The first direct hit stays first. Remaining seats alternate between direct
hits and graph neighbours; text expansion fills seats after graph neighbours.
Selection never changes a candidate's evidence or confirmation class. A
one-item budget cannot hold both an anchor and its neighbour.
"""
from collections import Counter
from .diversity import mmr


def select_candidates(candidates: list[dict], limit: int, *, diverse: bool = False) -> tuple[list[dict], dict]:
    direct, graph, text = [], [], []
    seen = set()
    for item in candidates:
        key = item.get("memory_id")
        if key in seen:
            continue
        seen.add(key)
        if item.get("reason") == "multihop_neighbour":
            graph.append(item)
        elif item.get("reason") == "multihop_expansion":
            text.append(item)
        else:
            direct.append(item)
    if diverse:
        direct = mmr(direct, limit)
        graph = mmr(graph, limit)
        text = mmr(text, limit)
    expanded = iter(graph + text)
    direct_iter = iter(direct)
    chosen = []
    while len(chosen) < limit:
        added = False
        for lane in (direct_iter, expanded):
            item = next(lane, None)
            if item is not None and len(chosen) < limit:
                chosen.append(item)
                added = True
        if not added:
            break
    return chosen, dict(Counter(item.get("classification", "UNKNOWN") for item in chosen))
