"""Offline direct-request projection of reviewed commitment candidates."""

from wsc.csm.commitment_projection import reviewed_commitments_from_mentions
from wsc.csm.contracts import CSMError, parse_instant


def candidate_scope(system, question, *, now, cutoff_turn):
    scope = {'now': now, 'cutoff_turn': cutoff_turn}
    passages = system.search_candidates(question, **scope, limit=10, distinct_passages=True)['passages']
    # A reply can outrank the user's statement within the same exchange. Re-open
    # the strongest turns and require a literal passage match to the review.
    turns = list(dict.fromkeys(passage['turn'] for passage in passages))[:6]
    if turns:
        local = system.search_within_originals(question, turns, **scope, per_turn=3)['passages']
        passages = list({(row['turn'], row['field'], row['start'], row['end']): row
                         for row in passages + local}.values())
    found = system.commitment_candidates_for_passages(passages, **scope)
    keys = tuple(dict.fromkeys(row['binding_key'] for row in found['candidates']))
    if keys:
        return keys
    clock = parse_instant(now)
    visible = system._search_scope(now, cutoff_turn, 10)
    try:
        matches = reviewed_commitments_from_mentions(
            system.csm, text=question, now=now, source_until=max(visible.values(), default=clock).isoformat(),
            visible_source_ids={f'chat/{index + 1}' for index in visible})
    except CSMError as error:
        if str(error) not in ('property_journal_not_initialized', 'entity_registry_not_initialized'):
            raise
        return ()
    keys = tuple(row['binding_key'] for row in matches)
    return keys
