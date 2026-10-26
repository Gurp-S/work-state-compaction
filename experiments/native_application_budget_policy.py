"""Opt-in phase allocation proposal; arm/study caps remain unchanged.

This changes allocation only. A replayed prefix is not a completed task or a
qualification to resume a study with uncertain accounting.
"""
from copy import deepcopy


def shared_arm_allocation(budgets):
    result = deepcopy(budgets)
    names = ('ordinary_phase', 'boundary_phase', 'per_arm', 'study')
    keys = {'max_responses', 'max_seconds', 'max_total_tokens'}
    if any(set(result[name]) != keys or any(type(value) is not int or value <= 0
            for value in result[name].values()) for name in names):
        raise ValueError('application_allocation_budget_invalid')
    if result['per_arm']['max_total_tokens'] > result['study']['max_total_tokens']:
        raise ValueError('application_allocation_study_smaller_than_arm')
    result['ordinary_phase']['max_total_tokens'] = result['per_arm']['max_total_tokens']
    result['ordinary_phase']['max_responses'] = result['per_arm']['max_responses']
    return result
