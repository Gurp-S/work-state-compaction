"""Opt-in date candidate order with one place for a literal deadline."""
from csm_bench22_recall_lanes import _segments
from wsc.csm.commitment_candidates import discover_commitment_candidates
from wsc.csm.contracts import parse_instant


def deadline_first(turns, dated_positions, *, now, cutoff_turn, limit=5):
    """Return visible candidate turns and the exact clause of a promoted deadline."""
    clock = parse_instant(now)
    visible = [position for position in dated_positions if 0 <= position < min(len(turns), cutoff_turn)
               and parse_instant(turns[position]['time']) <= clock]
    promoted = None
    for position in visible:
        turn = turns[position]
        text = turn['user']
        spans = discover_commitment_candidates(f'chat/{position + 1}', 'user', text, turn['time'])
        span = next((span for span in spans if span.kind == 'deadline_date' and span.day
                     and parse_instant(span.day[0]) <= clock < parse_instant(span.day[1])), None)
        if span is None:
            continue
        start, quote = next(((start, quote) for start, quote in _segments(text, True)
                             if start <= span.start and span.end <= start + len(quote)), (span.start, span.text))
        promoted = {'turn': position + 1, 'field': 'user', 'start': start, 'quote': quote,
                    'date_start': span.start, 'date_end': span.end, 'date_text': span.text}
        visible = [position, *(candidate for candidate in visible if candidate != position)]
        break
    return [position + 1 for position in visible[:limit]], promoted
