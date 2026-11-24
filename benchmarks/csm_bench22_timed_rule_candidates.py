"""Find already reviewed rule sources without resolving request applicability."""
from csm_bench22_timed_rule import _rule_at
from wsc.csm.contracts import parse_instant


def find_timed_rule_candidates(system, question, *, now, cutoff_turn, rules, limit=8):
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('timed_rule_candidate_limit_invalid')
    if type(cutoff_turn) is not int or cutoff_turn < 0:
        raise ValueError('timed_rule_cutoff_invalid')
    clock = parse_instant(now)
    matches = {}
    for rule in rules:
        anchors = rule['anchors']
        binding = rule['binding']
        quote = binding['source'].quote
        if (not isinstance(anchors, (tuple, list)) or not anchors
                or any(not isinstance(anchor, str) or anchor != anchor.strip()
                       or len(anchor) < 2 or anchor not in quote for anchor in anchors)):
            raise ValueError('timed_rule_anchor_not_in_source')
        matched = tuple(dict.fromkeys(anchor for anchor in anchors if anchor in question))
        if not matched:
            continue
        expired = clock >= parse_instant(binding['valid_until'])
        item = _rule_at(system, now=now, cutoff_turn=cutoff_turn, historical=expired, **binding)
        if item is None:
            continue
        row = {'scope': item['slot'], 'valid_from': item['valid_from'],
               'valid_until': item['valid_until'], 'source_observed_at': item['source_observed_at'],
               'window_status': 'elapsed' if expired else 'within_window',
               'matching_anchors': matched, 'source_spans': item['source_spans']}
        span = item['source_spans'][0]
        key = (span['event_id'], span['quote'], row['scope'], row['valid_from'], row['valid_until'])
        if key in matches:
            row['matching_anchors'] = tuple(dict.fromkeys((*matches[key]['matching_anchors'], *matched)))
        matches[key] = row
    candidates = sorted(matches.values(), key=lambda row: (-len(row['matching_anchors']),
                                                           -max(map(len, row['matching_anchors']))))
    return {'resolution': 'pending_request_binding' if candidates else 'no_reviewed_match',
            'candidates': candidates[:limit], 'truncated': len(candidates) > limit}
