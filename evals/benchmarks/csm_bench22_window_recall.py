"""Offline source candidates for explicitly stated multi-day windows."""
from csm_bench22_raw_memory import RawMemoryBench22
from wsc.csm.calendar_windows import find_source_calendar_windows
from wsc.csm.contracts import parse_instant


class WindowRecallBench22(RawMemoryBench22):
    def __init__(self, **options):
        self.window_spans = []
        super().__init__(**options)

    def _index_source(self, turn):
        super()._index_source(turn)
        for start, end, quote, window in find_source_calendar_windows(turn['user'], turn['time']):
            self.window_spans.append((turn['turn'], start, end, quote, window))

    def rewind(self, token):
        super().rewind(token)
        while self.window_spans and self.window_spans[-1][0] > token:
            self.window_spans.pop()

    def search_calendar_windows(self, *, now, cutoff_turn, limit=5):
        """Return active calendar intervals as candidates without binding a request."""
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('invalid_source_search_limit')
        if type(cutoff_turn) is not int or cutoff_turn < 0:
            raise ValueError('invalid_source_cutoff')
        clock = parse_instant(now)
        matches = []
        for turn, start, end, quote, window in reversed(self.window_spans):
            if (turn > cutoff_turn or parse_instant(self.turns[turn - 1]['time']) > clock
                    or not parse_instant(window[0]) <= clock < parse_instant(window[1])):
                continue
            source = self.read_original(turn, now=now, cutoff_turn=cutoff_turn)
            if source['user'][start:end] != quote:
                raise ValueError('source_calendar_window_mismatch')
            matches.append({'turn': turn, 'field': 'user', 'start': start, 'end': end, 'quote': quote,
                            'window_start': window[0], 'window_end': window[1],
                            'scope': 'calendar_window_match_only'})
            if len(matches) == limit:
                break
        return matches
