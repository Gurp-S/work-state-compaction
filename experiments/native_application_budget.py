"""Atomic per-arm/study admission for concurrent receipt-boundary budgets."""
from threading import Lock
import time
import math


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


class StudyBudget:
    def __init__(self, arm_limits, study_limits, *, clock=time.monotonic):
        keys = {'max_total_tokens', 'max_responses', 'max_seconds'}
        require(set(study_limits) == keys and arm_limits, 'application_budget_shape_invalid')
        require(all(set(v) == keys for v in arm_limits.values()), 'application_arm_budget_shape_invalid')
        require(all(type(n) is int and n > 0 for spec in [study_limits, *arm_limits.values()] for n in spec.values()),
                'application_budget_value_invalid')
        self.arms = {k: dict(limits=dict(v), tokens=0, responses=0, started=None, seconds=0., peer_wait_seconds=0., stopped=False) for k, v in arm_limits.items()}
        self.study = dict(limits=dict(study_limits), tokens=0, responses=0, uncertain=False)
        self.clock, self.started = clock, clock()
        self.lock, self.inflight, self.receipt_ids = Lock(), {}, set()
        self.sequence = 0

    def reserve(self, arm, limits):
        with self.lock:
            require(arm in self.arms and not self.study['uncertain'], 'application_budget_unknown_or_arm_missing')
            require(set(limits) == {'max_total_tokens', 'max_responses', 'max_seconds'}
                    and all(type(v) is int and v > 0 for v in limits.values()), 'application_phase_budget_invalid')
            state, now = self.arms[arm], self.clock()
            require(not state['stopped'] and not any(v['arm'] == arm for v in self.inflight.values()),
                    'application_arm_stopped_or_active')
            if state['started'] is None:
                state['started'] = now
            study_seconds = self.study['limits']['max_seconds'] - (now - self.started)
            arm_seconds = state['limits']['max_seconds'] - (now - state['started'] - state['peer_wait_seconds'])
            granted = dict(max_seconds=int(min(limits['max_seconds'], study_seconds, arm_seconds)))
            for field, spent in [('max_total_tokens', 'tokens'), ('max_responses', 'responses')]:
                held = sum(v['limits'][field] for v in self.inflight.values())
                granted[field] = min(limits[field], state['limits'][field] - state[spent],
                                     self.study['limits'][field] - self.study[spent] - held)
            require(all(value > 0 for value in granted.values()), 'application_cumulative_budget_exhausted')
            ticket = f'{self.sequence:06d}'
            self.sequence += 1
            self.inflight[ticket] = dict(arm=arm, limits=granted, started=now)
            return ticket, dict(granted)

    def record_peer_wait(self, arm, seconds):
        with self.lock:
            require(arm in self.arms and type(seconds) in (int, float) and seconds >= 0,
                    'application_peer_wait_invalid')
            require(math.isfinite(seconds) and self.arms[arm]['started'] is not None,
                    'application_peer_wait_invalid')
            require(not any(v['arm'] == arm for v in self.inflight.values()), 'application_peer_wait_during_model_call')
            self.arms[arm]['peer_wait_seconds'] += seconds

    def mark_unknown(self, arm, receipts=()):
        """Freeze admission and retain newly observed late/unattributed spend."""
        with self.lock:
            require(arm in self.arms, 'application_budget_arm_missing')
            self.study['uncertain'] = True
            self.arms[arm]['stopped'] = True
            tokens, responses = 0, 0
            for receipt in receipts:
                rid, amount = receipt.get('response_id'), receipt.get('usage', {}).get('total_tokens')
                if isinstance(rid, str) and rid and rid not in self.receipt_ids and type(amount) is int and amount >= 0:
                    self.receipt_ids.add(rid)
                    tokens += amount
                    responses += 1
            for value in (self.arms[arm], self.study):
                value['tokens'] += tokens
                value['responses'] += responses
            return dict(known_added_tokens=tokens, known_added_responses=responses, complete=False)

    def settle(self, ticket, phase):
        with self.lock:
            require(ticket in self.inflight, 'application_budget_ticket_missing_or_settled')
            grant = self.inflight[ticket]
            def receipt_check(ok, reason):
                if not ok:
                    self.study['uncertain'] = True
                    self.arms[grant['arm']]['stopped'] = True
                require(ok, reason)
            receipt_check(isinstance(phase, dict), 'application_budget_phase_invalid')
            receipts = phase.get('receipts', {})
            receipt_check(isinstance(receipts, dict), 'application_budget_receipts_invalid')
            entries = receipts.get('response_receipts', [])
            receipt_check(isinstance(entries, list), 'application_budget_receipts_invalid')
            receipt_check(all(isinstance(r, dict) and isinstance(r.get('usage'), dict) for r in entries),
                          'application_budget_receipts_invalid')
            receipt_check(bool(entries) or phase.get('usage_complete') is not True,
                          'application_budget_empty_complete_usage')
            new_ids = [r.get('response_id') for r in entries]
            receipt_check(all(isinstance(k, str) and k for k in new_ids) and len(set(new_ids)) == len(new_ids)
                    and not set(new_ids) & self.receipt_ids, 'application_budget_response_reused')
            receipt_check(all(type(r.get('usage', {}).get('total_tokens')) is int and r['usage']['total_tokens'] >= 0 for r in entries),
                    'application_budget_usage_invalid')
            known = sum(r['usage']['total_tokens'] for r in entries)
            state = self.arms[grant['arm']]
            for value in (state, self.study):
                value['tokens'] += known
                value['responses'] += len(entries)
            state['seconds'] += max(0., self.clock() - grant['started'])
            self.receipt_ids.update(new_ids)
            complete = phase.get('usage_complete') is True
            if not complete:
                self.study['uncertain'] = True
            exceeded = known > grant['limits']['max_total_tokens'] or len(entries) > grant['limits']['max_responses']
            state['stopped'] |= not complete or exceeded or phase.get('failure') is not None
            del self.inflight[ticket]
            return dict(known_total_tokens=known, known_responses=len(entries), usage_complete=complete,
                        observed_overshoot=exceeded, arm_stopped=state['stopped'], study_unknown=self.study['uncertain'])

    def snapshot(self):
        with self.lock:
            return dict(arms={k: dict(v, limits=dict(v['limits'])) for k, v in self.arms.items()},
                study=dict(self.study, limits=dict(self.study['limits'])),
                inflight={k: {**v, 'limits': dict(v['limits'])} for k, v in self.inflight.items()},
                response_ids=sorted(self.receipt_ids), cash=None,
                scope='Response-boundary token admission; in-flight overshoot retained; not provider-side hard cap or crash recovery')
