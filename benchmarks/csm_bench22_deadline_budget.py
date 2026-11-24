"""Compare whole-turn ordering that retains existing literal deadline sources."""
from csm_bench22_whole_turn_budget import fit_whole_turns
from wsc.csm.cem.commitment_candidates import discover_commitment_candidates


def fit_with_deadline_sources(question, *, existing, state_turns, ranked, read_original, render, allowance):
    protected = set(state_turns)
    for turn in existing.keys() - protected:
        source = read_original(turn)
        spans = discover_commitment_candidates(f'chat/{turn}', 'user', source['user'], source['time'])
        if any(span.kind == 'deadline_date' and span.day for span in spans):
            protected.add(turn)
    return fit_whole_turns(question, existing=existing, state_turns=protected, ranked=ranked,
                           read_original=read_original, render=render, allowance=allowance)
