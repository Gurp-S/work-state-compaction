"""Exact structured citation coverage, separate from task correctness.

The private expected assertions never belong to compression material. A byte
match proves only that a cited source field has that value, not free-text truth
or present applicability. Task acceptors and constraint checks stay separate.
"""
from hashlib import sha256
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def seal(value):
    return sha256(canonical(value).encode('utf-8')).hexdigest()


def field_at(value, path):
    if type(path) is not list:
        raise ValueError('field_path_invalid')
    for step in path:
        if type(step) is str and type(value) is dict and step in value:
            value = value[step]
        elif type(step) is int and type(value) is list and 0 <= step < len(value):
            value = value[step]
        else:
            raise ValueError('field_path_missing_or_invalid')
    return value


def evaluate(assertions, expected, sources):
    """sources[id] is {data: original JSON value, sha256: seal(data)}.

All arms use the same assertion IDs, output contract and private source map.
Denominators are fixed by required IDs; omitting claims cannot inflate coverage.
An old field may match exactly while the current expected answer is different.
    """
    if type(assertions) is not list or type(expected) is not dict or type(sources) is not dict:
        raise ValueError('assertion_input_invalid')
    for source in sources.values():
        if type(source) is not dict or set(source) != {'data', 'sha256'} or source['sha256'] != seal(source['data']):
            raise ValueError('source_catalog_integrity_mismatch')
    submitted = {}
    for claim in assertions:
        if type(claim) is not dict or not {'assertion_id', 'value'} <= claim.keys() or not set(claim) <= {
                'assertion_id', 'value', 'source_id', 'field_path'}:
            raise ValueError('assertion_shape_invalid')
        identity = claim['assertion_id']
        if type(identity) is not str or identity not in expected or identity in submitted:
            raise ValueError('assertion_identity_invalid_or_duplicate')
        canonical(claim['value'])
        submitted[identity] = claim
    details = []
    for identity, answer in expected.items():
        claim = submitted.get(identity)
        correct = claim is not None and canonical(claim['value']) == canonical(answer)
        citation_matches = False
        citation_error = None
        if claim is None:
            citation_error = 'assertion_missing'
        elif 'source_id' not in claim or 'field_path' not in claim:
            citation_error = 'citation_missing'
        elif type(claim['source_id']) is not str or claim['source_id'] not in sources:
            citation_error = 'citation_source_unknown'
        else:
            try:
                cited = field_at(sources[claim['source_id']]['data'], claim['field_path'])
                citation_matches = canonical(cited) == canonical(claim['value'])
                if not citation_matches:
                    citation_error = 'citation_field_value_mismatch'
            except ValueError as error:
                citation_error = str(error)
        details.append(dict(assertion_id=identity, submitted=claim is not None,
                            answer_correct=correct, citation_byte_match=citation_matches,
                            citation_error=citation_error))
    count = len(expected)
    matched = sum(r['citation_byte_match'] for r in details)
    correct = sum(r['answer_correct'] for r in details)
    return dict(required_assertions=count, submitted_assertions=len(submitted),
                citation_byte_matches=matched, citation_byte_match_rate=matched/count if count else None,
                missing_or_nonmatching_citation_rate=(count-matched)/count if count else None,
                exact_answer_correct=correct, exact_answer_accuracy=correct/count if count else None,
                unknown_source_citations=sum(r['citation_error'] == 'citation_source_unknown' for r in details),
                free_text_semantic_support_rate=None, task_success=None, details=details,
                scope='Exact JSON source field correspondence only; task success comes from independent acceptors.')
