"""Opt-in durable dispatch binding around the existing StudyBudget.

One coordinator owns a ledger, concurrent worker threads share it. Existing
ledgers are inspection-only: reopening never resumes or replays model work.
This module does not launch a model or authorize dispatch by itself.
"""
from copy import deepcopy
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from threading import RLock
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'experiments'))
from native_application_budget import StudyBudget, require


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class _ActiveClock:
    """Union of active dispatch intervals; idle/quota waiting is excluded."""
    def __init__(self, clock):
        self.clock, self.elapsed, self.anchor = clock, 0., None

    def now(self):
        return self.elapsed + (0. if self.anchor is None else self.clock()-self.anchor)

    def start(self):
        if self.anchor is None:
            self.anchor = self.clock()

    def stop(self):
        self.elapsed = self.now()
        self.anchor = None


class DispatchBudget:
    def __init__(self, path, runs, study_limits, *, arm_token_ceiling=15000000, clock=time.monotonic):
        require(type(arm_token_ceiling) is int and arm_token_ceiling > 0, 'matrix_arm_ceiling_invalid')
        require(isinstance(runs, dict) and bool(runs), 'matrix_runs_missing')
        for identity, spec in runs.items():
            require(type(identity) is str and bool(identity) and isinstance(spec, dict), 'matrix_run_invalid')
            require(set(spec) == {'arm', 'limits', 'binding'} and type(spec['arm']) is str
                    and bool(spec['arm']) and isinstance(spec['binding'], dict), 'matrix_run_binding_invalid')
            encoded(spec)
        self.clock = _ActiveClock(clock)
        self.budget = StudyBudget({k: v['limits'] for k, v in runs.items()}, study_limits, clock=self.clock.now)
        self.runs = {k: dict(spec=deepcopy(v), status='planned', result=None) for k, v in runs.items()}
        self.arm_ceiling = arm_token_ceiling
        self.lock, self.tickets, self.phase_ids = RLock(), {}, set()
        self.closed, self.poisoned = False, False
        self.path = Path(path).resolve()
        # Exclusive create prevents a restart from silently resetting counters.
        with self.path.open('xb'):
            pass
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity TEXT, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE current(singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL)')
        self._persist('registered', None, dict(runs=runs, study_limits=study_limits))

    def _snapshot(self):
        return dict(status='closed' if self.closed else 'frozen' if self.poisoned or self.budget.study['uncertain'] else 'active',
            runs=deepcopy(self.runs), budget=self.budget.snapshot(), tickets=deepcopy(self.tickets),
            active_seconds=self.clock.now(), arm_token_ceiling=self.arm_ceiling,
            scope='Response-boundary budget; in-flight overshoot retained. Existing ledger cannot dispatch again.')

    def _persist(self, kind, identity, payload):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO events(kind,identity,payload) VALUES(?,?,?)', (kind, identity, encoded(payload)))
            self.db.execute('INSERT OR REPLACE INTO current VALUES(1,?)', (encoded(self._snapshot()),))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            self.poisoned = True
            raise

    def reserve(self, run_id, phase_id, limits, *, input_binding=None):
        with self.lock:
            require(not self.closed and not self.poisoned, 'matrix_ledger_not_live')
            require(run_id in self.runs and self.runs[run_id]['status'] in ('planned', 'running'), 'matrix_run_not_dispatchable')
            require(type(phase_id) is str and bool(phase_id) and (run_id, phase_id) not in self.phase_ids,
                    'matrix_phase_already_dispatched_or_invalid')
            require(not any(v['run_id'] == run_id for v in self.tickets.values()), 'matrix_run_already_active')
            run = self.runs[run_id]
            arm = run['spec']['arm']
            members = {k for k, value in self.runs.items() if value['spec']['arm'] == arm}
            spent = sum(self.budget.arms[k]['tokens'] for k in members)
            held = sum(v['limits']['max_total_tokens'] for v in self.budget.inflight.values() if v['arm'] in members)
            remaining = self.arm_ceiling - spent - held
            require(remaining > 0, 'matrix_arm_cumulative_budget_exhausted')
            # Let StudyBudget validate all caller-supplied limits before clamping.
            require(set(limits) == {'max_total_tokens', 'max_responses', 'max_seconds'}
                    and all(type(v) is int and v > 0 for v in limits.values()), 'matrix_phase_limits_invalid')
            request = dict(limits, max_total_tokens=min(limits['max_total_tokens'], remaining))
            self.clock.start()
            state = self.budget.arms[run_id]
            if state['started'] is not None:
                state['peer_wait_seconds'] = max(0., self.clock.now()-state['started']-state['seconds'])
            try:
                ticket, granted = self.budget.reserve(run_id, request)
            except BaseException:
                if not self.budget.inflight:
                    self.clock.stop()
                raise
            self.phase_ids.add((run_id, phase_id))
            run['status'] = 'running'
            binding_sha = sha256(encoded(run['spec']['binding']).encode('utf-8')).hexdigest()
            record = dict(run_id=run_id, phase_id=phase_id, limits=granted, binding_sha256=binding_sha)
            if input_binding is not None:
                record['input_binding'] = deepcopy(input_binding)
            self.tickets[ticket] = record
            # Caller can send only after this transaction committed successfully.
            self._persist('reserved', ticket, record)
            return dict(ticket=ticket, **deepcopy(record))

    def settle(self, ticket, phase):
        with self.lock:
            require(not self.closed and not self.poisoned and ticket in self.tickets, 'matrix_ticket_not_live')
            record = self.tickets[ticket]
            elapsed = self.clock.now()-self.budget.inflight[ticket]['started']
            try:
                result = self.budget.settle(ticket, phase)
            except Exception as error:
                # Keep valid known receipts even when the rest of the phase is malformed.
                receipts = phase.get('receipts', {}) if isinstance(phase, dict) else {}
                entries = receipts.get('response_receipts', []) if isinstance(receipts, dict) else []
                valid = [r for r in entries if isinstance(r, dict) and isinstance(r.get('usage'), dict)] if isinstance(entries, list) else []
                self.budget.mark_unknown(record['run_id'], valid)
                # Freeze new dispatch, but allow other already-active peers to settle.
                del self.budget.inflight[ticket]
                del self.tickets[ticket]
                if not self.budget.inflight:
                    self.clock.stop()
                self._persist('settlement_rejected', ticket, dict(phase=phase, error=str(error)))
                raise
            result['observed_time_overrun'] = elapsed > record['limits']['max_seconds']
            result['active_phase_seconds'] = elapsed
            if result['observed_time_overrun']:
                self.budget.arms[record['run_id']]['stopped'] = True
                result['arm_stopped'] = True
            del self.tickets[ticket]
            if not self.budget.inflight:
                self.clock.stop()
            self._persist('settled', ticket, dict(phase=phase, result=result))
            return result

    def remaining(self, ticket):
        """Host setup/compression/I/O belongs inside the reserved interval.

        Read immediately before calling execute_stage: its relative deadline
        must not restart the original phase allowance after host preparation.
        This is no provider-side cancellation or output-token hard cap.
        """
        with self.lock:
            require(not self.closed and not self.poisoned and ticket in self.tickets, 'matrix_ticket_not_live')
            require(not self.budget.study['uncertain'], 'matrix_budget_unknown')
            record = self.tickets[ticket]
            elapsed = self.clock.now()-self.budget.inflight[ticket]['started']
            seconds = int(record['limits']['max_seconds']-elapsed)
            require(seconds > 0, 'matrix_phase_time_exhausted')
            return dict(record['limits'], max_seconds=seconds)

    def bind_input(self, ticket, value):
        """Seal a generated phase request before inference, exactly once."""
        with self.lock:
            require(not self.closed and not self.poisoned and ticket in self.tickets, 'matrix_ticket_not_live')
            require('input_binding' not in self.tickets[ticket] and isinstance(value,dict) and bool(value),
                    'matrix_phase_input_already_bound_or_invalid')
            encoded(value)
            self.tickets[ticket]['input_binding']=deepcopy(value)
            self._persist('input_bound',ticket,value)

    def finish(self, run_id, result):
        with self.lock:
            require(not self.closed and not self.poisoned and run_id in self.runs, 'matrix_finish_not_live')
            run = self.runs[run_id]
            require(run['status'] == 'running' and not any(v['run_id'] == run_id for v in self.tickets.values()),
                    'matrix_run_unstarted_closed_or_active')
            require(isinstance(result, dict) and type(result.get('success')) is bool, 'matrix_task_result_invalid')
            require(not result['success'] or (not self.budget.arms[run_id]['stopped']
                    and not self.budget.study['uncertain']), 'matrix_incomplete_run_cannot_succeed')
            run.update(status='finished', result=deepcopy(result))
            self._persist('finished', run_id, result)

    def snapshot(self):
        with self.lock:
            return self._snapshot()

    def close(self):
        with self.lock:
            if self.closed:
                return
            if self.budget.inflight:
                self.budget.study['uncertain'] = True
            for run in self.runs.values():
                if run['status'] == 'running':
                    run.update(status='interrupted', result=dict(success=False, reason='coordinator_closed_before_run_finish'))
            self.clock.stop()
            self.closed = True
            try:
                self._persist('closed', None, dict(inflight_retained=bool(self.budget.inflight)))
            finally:
                self.db.close()


def inspect_ledger(path):
    """Read only; never creates a ledger or replays a reserved dispatch."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT state FROM current WHERE singleton=1').fetchone()[0])
        events = [dict(seq=n, kind=k, identity=i, payload=json.loads(p))
                  for n, k, i, p in db.execute('SELECT seq,kind,identity,payload FROM events ORDER BY seq')]
    return dict(state=state, events=events, inspection_only=True)
