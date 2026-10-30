"""Host-only nested timing. Components are caller labels, never causal claims."""
from contextlib import contextmanager
from threading import RLock, local
import time


def union_seconds(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end < start:
            raise ValueError('timing_clock_reversed')
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end-start for start, end in merged)


class PhaseTiming:
    def __init__(self, *, clock=time.perf_counter, cpu_clock=time.thread_time):
        self.clock, self.cpu_clock = clock, cpu_clock
        self.lock, self.local = RLock(), local()
        self.rows = []

    @contextmanager
    def measure(self, component):
        if type(component) is not str or not component:
            raise ValueError('timing_component_invalid')
        stack = getattr(self.local, 'stack', None)
        if stack is None:
            stack = self.local.stack = []
        with self.lock:
            row = dict(id=len(self.rows)+1, parent=stack[-1] if stack else None,
                       component=component, start=self.clock(), end=None,
                       thread_cpu_seconds=None, outcome='active')
            self.rows.append(row)
        stack.append(row['id'])
        cpu_start = self.cpu_clock()
        try:
            yield
        except BaseException:
            # No exception text or model-visible output is captured.
            with self.lock:
                row['outcome'] = 'error'
            raise
        else:
            with self.lock:
                row['outcome'] = 'success'
        finally:
            end, cpu_end = self.clock(), self.cpu_clock()
            stack.pop()
            with self.lock:
                row['end'] = end
                row['thread_cpu_seconds'] = cpu_end-cpu_start

    def call(self, component, function, *args, **kwargs):
        with self.measure(component):
            return function(*args, **kwargs)

    def snapshot(self):
        with self.lock:
            rows = [dict(row) for row in self.rows]
        complete = all(row['end'] is not None for row in rows)
        finished = [row for row in rows if row['end'] is not None]
        summaries = {}
        for row in finished:
            children = [(max(child['start'], row['start']), min(child['end'], row['end']))
                        for child in finished if child['parent'] == row['id']]
            wall = row['end']-row['start']
            if wall < 0 or row['thread_cpu_seconds'] < 0:
                raise ValueError('timing_clock_reversed')
            row['wall_seconds'] = wall
            row['exclusive_wall_seconds'] = wall-union_seconds(children)
            summary = summaries.setdefault(row['component'], dict(calls=0, errors=0,
                inclusive_wall_seconds=0., exclusive_wall_seconds=0., inclusive_thread_cpu_seconds=0.))
            summary['calls'] += 1
            summary['errors'] += row['outcome'] == 'error'
            summary['inclusive_wall_seconds'] += wall
            summary['exclusive_wall_seconds'] += row['exclusive_wall_seconds']
            summary['inclusive_thread_cpu_seconds'] += row['thread_cpu_seconds']
        return dict(complete=complete, spans=rows, components=summaries,
            measured_interval_union_seconds=union_seconds([(r['start'],r['end']) for r in finished]),
            scope='Inclusive nested and concurrent component times are not additive. '
                  'Uninstrumented work is unknown. HTTP includes network, provider and buffering; '
                  'thread CPU excludes child processes and remote compute. No causal noise subtraction.')
