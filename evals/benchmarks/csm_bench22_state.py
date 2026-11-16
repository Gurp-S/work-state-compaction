"""Gateway-backed state production for the Bench 2.2 adapter."""
from datetime import timedelta, timezone
import json
import re

from wsc.csm.commitment_candidates import discover_commitment_candidates
from wsc.csm.contracts import parse_instant
from wsc.csm.state_extraction import ModelStateExtractor, StateProducerResponseError


def parse_model_json(body):
    return json.loads(re.sub(r'\A\s*```(?:json)?\s*|\s*```\s*\Z', '', body, flags=re.I))


def gateway_extractor(gateway, *, retain_off_day=False):
    def ask(system, user, *, max_tokens):
        response = gateway.chat('deepseek-v4.1-flash', [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user},
        ], 'retrieve', 'state-extraction', temperature=0, max_tokens=max_tokens,
            thinking={'type': 'disabled'})
        try:
            choice = response['choices'][0]
            if choice['finish_reason'] != 'stop':
                raise StateProducerResponseError('state_producer_unfinished')
            return parse_model_json(choice['message']['content'])
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise StateProducerResponseError('state_producer_invalid_response') from error
    return ModelStateExtractor(ask, retain_off_day=retain_off_day)


class CalendarEvidence:
    """Index source day mentions, without inferring that they are events."""

    def __init__(self):
        self.days = {}

    def add(self, turn):
        # Assistant restatements can repeat an old relative date at a new time.
        candidates = discover_commitment_candidates(
            f'chat/{turn["turn"]}', 'user', turn['user'], turn['time'])
        for day in {c.day for c in candidates if c.day}:
            start, end = (parse_instant(bound).astimezone(timezone.utc) for bound in day)
            if parse_instant(turn['time']) < start:
                self.days.setdefault(start.date(), []).append((turn['turn'] - 1, start, end))

    def rewind(self, stop):
        for key in list(self.days):
            rows = self.days[key]
            while rows and rows[-1][0] >= stop:
                rows.pop()
            if not rows:
                del self.days[key]

    def matching(self, now, stop):
        clock = parse_instant(now).astimezone(timezone.utc)
        matches = {index for day in (clock.date(), clock.date() - timedelta(days=1))
                   for index, start, end in self.days.get(day, ())
                   if index < stop and start <= clock < end}
        return sorted(matches, reverse=True)
