"""Allocation arithmetic, not an upper bound on interrupted provider billing."""
from copy import deepcopy

KEYS={'max_total_tokens','max_responses','max_seconds'}


def remaining(reference,claims):
    values=[reference]+list(claims)
    if any(type(v) is not dict or set(v)!=KEYS or any(type(n) is not int or n<0 for n in v.values()) for v in values):
        raise ValueError('allocation_shape_invalid')
    result=deepcopy(reference)
    for claim in values[1:]:
        for key in KEYS:result[key]-=claim[key]
    if any(v<0 for v in result.values()):raise ValueError('allocation_exceeds_reference')
    return result
