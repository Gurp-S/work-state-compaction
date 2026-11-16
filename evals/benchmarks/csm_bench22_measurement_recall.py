"""Offline candidate discovery by explicit measurement type."""
import re

from csm_bench22_candidate_delivery import append_source_candidate
from csm_bench22_passage_binding import verify_passage
from csm_bench22_raw_memory import RawMemoryBench22


_ACTIVITY_QUERY = re.compile(r'活动量|运动量|步数|(?:走|行走)(?:了)?多少步')
_DAILY = re.compile(r'每天|日均|一天|手环')
_STEPS = re.compile(r'(?:[0-9]{2,}|[零〇一二三四五六七八九十百千万两]{2,})[多余]?步')


def _step_measurements(turn):
    text = turn['user']
    for paragraph in re.finditer(r'[^\n]+', text):
        body = paragraph.group()
        if not _DAILY.search(body):
            continue
        for match in re.finditer(r'[^。！？]+(?:[。！？]|$)', body):
            if not _STEPS.search(match.group()) or not _DAILY.search(match.group()):
                continue
            first = match.start()
            end = match.end()
            following = re.match(r'[^。！？]+(?:[。！？]|$)', body[end:])
            if following and _STEPS.search(following.group()) and end + following.end() - first <= 155:
                end += following.end()
            start = paragraph.start() + first
            stop = paragraph.start() + end
            if stop - start <= 155:
                yield {'turn': turn['turn'], 'field': 'user', 'start': start, 'end': stop,
                       'quote': text[start:stop]}


class MeasurementRecallBench22(RawMemoryBench22):
    """Find literal metric observations, leaving identity and applicability open."""

    def __init__(self):
        super().__init__()
        self.step_measurements = {}

    def _index_source(self, turn):
        super()._index_source(turn)
        first = next(_step_measurements(turn), None)
        if first is not None:
            self.step_measurements[turn['turn']] = first

    def rewind(self, token):
        super().rewind(token)
        self.step_measurements = {turn: row for turn, row in self.step_measurements.items() if turn <= token}

    def search_measurements(self, question, *, now, cutoff_turn, limit=3):
        visible = self._search_scope(now, cutoff_turn, limit)
        if not _ACTIVITY_QUERY.search(question):
            return {'metric': None, 'candidates': [], 'exhaustive': False}
        candidates = []
        for turn in reversed(self.step_measurements):
            if turn - 1 not in visible:
                continue
            # Keep the earliest matching clause of that turn, including its paired correction.
            first = self.step_measurements[turn]
            verify_passage(first, self.read_original(turn, now=now, cutoff_turn=cutoff_turn))
            candidates.append(first)
            if len(candidates) == limit:
                break
        return {'metric': 'daily_steps', 'candidates': candidates, 'exhaustive': False}

    def supplement_measurements(self, result, question, *, now, cutoff_turn):
        """Append one scoped candidate using only spare final prompt capacity."""
        candidates = self.search_measurements(question, now=now, cutoff_turn=cutoff_turn, limit=1)['candidates']
        if not candidates:
            return result
        return append_source_candidate(self, result, candidates[0], result.state_items,
                                       now=now, cutoff_turn=cutoff_turn, label='日均步数候选',
                                       reason='measurement_request_binding_unverified')
