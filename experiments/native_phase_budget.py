"""Pre-registered per-phase limits, with legacy runs retaining their old caps.

Token limits are observed at receipt boundaries; an in-flight response can
overshoot. Final accounting reports that overshoot, never trims its cost.
"""
from dataclasses import dataclass
import math


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


@dataclass(frozen=True)
class PhaseBudget:
    responses: int
    deadline: float
    tokens: int | None
    explicit: bool

    @classmethod
    def resolve(cls, registration, *, begin, deadline, compact=False, spent_responses=0):
        require(type(spent_responses) is int and 0 <= spent_responses < 10, 'phase_spent_responses_invalid')
        require(math.isfinite(deadline) and deadline > begin, 'phase_deadline_exhausted')
        if 'phase_budget' not in registration:
            return cls(10 - spent_responses, min(deadline, begin + 240) if compact else deadline, None, False)
        spec = registration['phase_budget']
        require(isinstance(spec, dict) and set(spec) == {'max_responses', 'max_seconds', 'max_total_tokens'},
                'phase_budget_shape_invalid')
        require(all(type(spec[k]) is int and spec[k] > 0 for k in spec), 'phase_budget_value_invalid')
        require(spent_responses == 0, 'phase_budget_legacy_spend_conflict')
        return cls(spec['max_responses'], min(deadline, begin + spec['max_seconds']), spec['max_total_tokens'], True)

    def stop_reason(self, receipts, *, final=False):
        if final and not self.explicit:
            return None
        responses = receipts['response_count']
        tokens = receipts['all_usage']['total_tokens']
        if self.tokens is not None and (tokens > self.tokens or (tokens == self.tokens and not final)):
            return 'registered_token_cap'
        if responses > self.responses or (responses == self.responses and not final):
            return 'registered_response_cap'
        return None

    def observation(self, receipts):
        return {'registered': self.explicit, 'response_limit': self.responses, 'token_limit': self.tokens,
                'observed_responses': receipts['response_count'],
                'observed_total_tokens': receipts['all_usage']['total_tokens'],
                'scope': 'Receipt-boundary limits; in-flight response overshoot is counted in full.'}
