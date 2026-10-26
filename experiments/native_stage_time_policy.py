"""Opt-in proposal: ordinary phases share the existing arm time allowance."""
from copy import deepcopy

MODE = 'arm_shared_ordinary_time_v1'


def propose(conditions):
    result = deepcopy(conditions)
    budgets = result['budgets']
    ordinary, arm = budgets['ordinary_phase'], budgets['per_arm']
    if (type(ordinary['max_seconds']) is not int or type(arm['max_seconds']) is not int
            or not 0 < ordinary['max_seconds'] <= arm['max_seconds']):
        raise ValueError('ordinary_arm_time_allocation_invalid')
    ordinary['max_seconds'] = arm['max_seconds']
    result['ordinary_time_policy'] = MODE
    return result
