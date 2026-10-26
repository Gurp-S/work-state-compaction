"""Carry closed failed studies into a separately authorized qualification.

Unknown historical usage stays unknown. Its original occupied arm allocation
is withheld from new admission, not reported as actual spend or a proven bound.
The frozen historical StudyBudget is never resumed or rewritten.
"""
from copy import deepcopy
import math


def qualification_envelope(snapshot, protocol_phases, elapsed_wall_seconds):
    if snapshot['inflight'] or not math.isfinite(elapsed_wall_seconds) or elapsed_wall_seconds < 0:
        raise ValueError('campaign_history_not_closed')
    known = {key: snapshot['study'][key] for key in ('tokens','responses')}
    if any(type(value) is not int or value < 0 for value in known.values()):
        raise ValueError('campaign_history_usage_invalid')
    occupied = [arm for arm in snapshot['arms'].values() if arm['started'] is not None]
    if any(sum(arm[key] for arm in occupied) != known[key] for key in known):
        raise ValueError('campaign_history_arm_total_mismatch')
    held = {key: sum(max(arm['limits'][limit], arm[key])-arm[key] for arm in occupied)
            for key,limit in (('tokens','max_total_tokens'),('responses','max_responses'))}
    ids = set(snapshot['response_ids'])
    protocol = dict(tokens=0,responses=0)
    for phase in protocol_phases:
        if phase.get('usage_complete') is not True:
            raise ValueError('campaign_protocol_usage_unknown')
        for receipt in phase['receipts']['response_receipts']:
            rid, amount = receipt['response_id'], receipt['usage']['total_tokens']
            if not isinstance(rid,str) or not rid or rid in ids or type(amount) is not int or amount < 0:
                raise ValueError('campaign_protocol_receipt_invalid_or_reused')
            ids.add(rid)
            protocol['tokens'] += amount
            protocol['responses'] += 1
    caps = deepcopy(snapshot['study']['limits'])
    caps['max_total_tokens'] -= known['tokens'] + held['tokens'] + protocol['tokens']
    caps['max_responses'] -= known['responses'] + held['responses'] + protocol['responses']
    caps['max_seconds'] -= math.ceil(elapsed_wall_seconds)
    if any(value <= 0 for value in caps.values()):
        raise ValueError('campaign_admission_allocation_exhausted')
    return dict(remaining_limits=caps,original_limits=deepcopy(snapshot['study']['limits']),
        historical_known=known,historical_complete_usage=None if snapshot['study']['uncertain'] else known,
        historical_ledger_frozen=True,historical_uncertainty=snapshot['study']['uncertain'],
        withheld_unused_arm_allocation=held,protocol_known=protocol,
        elapsed_execution_wall_seconds=elapsed_wall_seconds,
        reservation_scope='Withheld original arm allocation; not a proven upper bound on unknown spend',
        total_campaign_usage_complete=not snapshot['study']['uncertain'])
