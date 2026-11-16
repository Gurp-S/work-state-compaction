"""Bind the lexical corpus and state query to the same visible observations."""
from bench22.systems import IncBM25, rrf
from csm_bench22_fast_bm25 import fast_top

from wsc.csm.contracts import parse_instant


def visible_observations(turns, stop, clock):
    observations = {}
    for index, turn in enumerate(turns[:stop]):
        observed = parse_instant(turn['time'])
        if observed <= clock:
            observations[index] = observed
    return observations


def rank_visible(question, turns, visible, user_index, full_index, *, lane_limit=32, top=fast_top):
    # The official harness feeds only the visible prefix. Reuse the incremental
    # indexes in that common case. Otherwise even term statistics must be scoped.
    if len(visible) == len(turns):
        return rrf([top(user_index, question, lane_limit), top(full_index, question, lane_limit)])
    if not visible:
        return []
    user = IncBM25(k1=user_index.k1, b=user_index.b)
    full = IncBM25(k1=full_index.k1, b=full_index.b)
    positions = list(visible)
    for index in positions:
        turn = turns[index]
        user.add(turn['user'])
        full.add(turn['user'] + '\n' + turn['assistant'])
    return [positions[index] for index in rrf([top(user, question, lane_limit), top(full, question, lane_limit)])]
