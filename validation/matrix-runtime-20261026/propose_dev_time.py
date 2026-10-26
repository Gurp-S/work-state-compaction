"""Offline proposed conditions, with all existing caps except phase time fixed."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save
from native_stage_time_policy import propose
from native_application_budget import StudyBudget

OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1')
registration = read(OUT / 'registration.json')
before = registration['conditions']
after = propose(before)
assert before['budgets']['ordinary_phase']['max_seconds'] == 600
assert after['budgets']['ordinary_phase']['max_seconds'] == 2700
for field in ('max_total_tokens', 'max_responses'):
    assert before['budgets']['ordinary_phase'][field] == after['budgets']['ordinary_phase'][field]
for field in ('boundary_phase', 'per_arm', 'study'):
    assert before['budgets'][field] == after['budgets'][field]
# Real admission implementation, synthetic elapsed clocks. No inferred task completion.
grants = {}
for label, conditions in [('before', before), ('proposed', after)]:
    now = [0.]
    budget = StudyBudget({'C': conditions['budgets']['per_arm']}, registration['envelope']['remaining_limits'], clock=lambda: now[0])
    ticket, granted = budget.reserve('C', conditions['budgets']['ordinary_phase'])
    grants[label] = granted
assert grants['before']['max_seconds'] == 600 and grants['proposed']['max_seconds'] == 2700
now = [0.]
budget = StudyBudget({'C': after['budgets']['per_arm']}, registration['envelope']['remaining_limits'], clock=lambda: now[0])
budget.arms['C']['started'] = 0.
budget.arms['C']['tokens'] = 5685419
budget.arms['C']['responses'] = 42
now[0] = 600.063
_, remaining = budget.reserve('C', after['budgets']['ordinary_phase'])
assert remaining == dict(max_seconds=2099, max_total_tokens=314581, max_responses=78)
proposal = dict(status='proposed_awaiting_user_choice', conditions=after,
    change='Only ordinary-phase time allocation; existing arm/study/token/response and boundary caps unchanged',
    scope='New future symmetric B/C conditions; original failed C is not resumed or reclassified',
    offline_grants=grants, synthetic_remaining_grant=remaining,
    model_calls=0, caveat='Synthetic admission only. No evidence that a later model final would fit remaining tokens or complete.')
save(OUT / 'proposed-shared-time.json', proposal)
print({key: proposal[key] for key in ('status', 'offline_grants', 'synthetic_remaining_grant', 'model_calls')})
