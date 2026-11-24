"""Keep short clarification exchanges attached to their source event."""
import re

from wsc.csm.contracts import parse_instant
from csm_bench22_previous_observation import locate_previous_observation, measurement_pair


_OMITTED_SPEAKER = re.compile(r'^(?:还|又)?(?:让|叫|劝|提醒|建议)(?:我们|我|你们|你)')


def _short_question(text):
    text = text.strip()
    return bool(text) and len(text) <= 20 and text.endswith(('?', '？')) and '\n' not in text


def attach_clarification(ranked, turns, visible, *, previous_candidates=()):
    """Expand one same-session anchor through a short question and attached replies."""
    for position, anchor in enumerate(ranked[:6], 1):
        bridge, answer = anchor + 1, anchor + 2
        if bridge not in visible or answer not in visible:
            continue
        start, end = (parse_instant(turns[index]['time']) for index in (anchor, answer))
        if start.date() != end.date() or not 0 <= (end - start).total_seconds() <= 300:
            continue
        middle = turns[bridge]
        if not _short_question(middle['assistant']):
            continue
        if len(middle['user'].strip()) > 20 or not turns[answer]['user'].strip():
            continue
        linked = [bridge, answer]
        tail = answer + 1
        if tail in visible:
            reply = turns[tail]['user'].strip()
            observed = parse_instant(turns[tail]['time'])
            if ('\n' not in reply and len(reply) <= 32 and _OMITTED_SPEAKER.match(reply)
                    and observed.date() == end.date() and 0 <= (observed - end).total_seconds() <= 300):
                linked.append(tail)
        previous = locate_previous_observation(anchor, answer, previous_candidates, turns, visible)
        ordered = [*ranked[:position], *linked, *ranked[position:]]
        comparison = None
        if previous is not None:
            ordered.append(previous)
            values = measurement_pair(turns[previous]['user'], turns[answer]['user'])
            if values is not None:
                comparison = {'older_turn': previous + 1, 'newer_turn': answer + 1,
                              'older_literal': values[0], 'newer_literal': values[1]}
        return list(dict.fromkeys(ordered)), comparison
    return ranked, None
