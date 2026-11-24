"""Narrow reviewed commitment candidates using literal source passages."""


def verify_passage(passage, original):
    field, start, end = (passage.get(key) for key in ('field', 'start', 'end'))
    if (field not in ('user', 'assistant') or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(original[field])
            or original[field][start:end] != passage.get('quote')):
        raise ValueError('commitment_candidate_passage_mismatch')


def narrow_passage_candidates(candidates, passages):
    narrowed = []
    for candidate in candidates:
        matches = [span for span in candidate['matched_evidence'] if any(
            span['event_id'] == f"chat/{passage['turn']}" and tuple(span['path']) == (passage['field'],)
            and span['quote'] in passage['quote'] for passage in passages)]
        if matches:
            narrowed.append({**candidate, 'matched_evidence': matches,
                             'matched_source_refs': sorted({span['event_id'] for span in matches})})
    return narrowed
