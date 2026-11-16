"""Group source-backed versions without changing the observations or their authority."""
from csm_bench22_previous_observation import measurement_pair


def group_observations(items, link, evidence_turns):
    if link is None or not {link['older_turn'], link['newer_turn']} <= set(evidence_turns):
        return items

    def matching(kind, turn, literal):
        return [row for row in items if row['kind'] == kind and row.get('status') == 'source_projection'
                and any(cite['turn'] == turn and cite['field'] == 'user' and literal in cite['quote']
                        for cite in row.get('citations', ()))]

    earlier = matching('HISTORICAL', link['older_turn'], link['older_literal'])
    later = matching('CURRENT_CONFIRMED', link['newer_turn'], link['newer_literal'])
    if len(earlier) != 1 or len(later) != 1:
        return items
    before, after = earlier[0], later[0]
    if before.get('entity') != after.get('entity') or not before.get('entity'):
        return items
    if measurement_pair(before['value'].split('；', 1)[0], after['value'].split('；', 1)[0]) != (
        link['older_literal'], link['newer_literal']
    ):
        return items
    citations = [*before['citations'], *after['citations']]
    pair = {'kind': 'OBSERVATION_COMPARISON', 'entity': after['entity'],
            'status': 'source_projection', 'source_turns': sorted(set(before['source_turns']) | set(after['source_turns'])),
            'citations': citations, 'observations': [before, after],
            'text': '[OBSERVATION_COMPARISON] 两次关联的原文观测\n' + before['text'] + '\n' + after['text']}
    return [pair if item is after else item for item in items if item is not before]
