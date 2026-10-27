"""Carry a closed execution allowance; calendar idle is not execution time."""
from copy import deepcopy
import math


def carry(envelope, operation_seconds):
    if any(type(value) not in (int,float) or not math.isfinite(value) or value<0 for value in operation_seconds):
        raise ValueError('execution_time_interval_invalid')
    result=deepcopy(envelope)
    spent=math.ceil(sum(operation_seconds))
    result['remaining_limits']['max_seconds']-=spent
    if result['remaining_limits']['max_seconds']<=0:
        raise ValueError('execution_time_allowance_exhausted')
    result['execution_time_policy']='recorded_execution_wall_only_v1'
    result['new_execution_seconds_charged']=spent
    return result
