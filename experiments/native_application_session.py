"""Opt-in native execution for application-study workers.

One session owns one native server/process tree. Stages use native tools and
append-only receipt accounting. C boundary policy and task quality stay outside
this transport; opening a session does not qualify a comparison.
"""
import json
from hashlib import sha256
from pathlib import Path
import queue
import os
import time

from native_evidence import digest, file_hash, manifest, records, save, usage
from native_owned_process import OwnedNativeRPC
from native_phase_budget import PhaseBudget
from native_rollout_snapshot import capture_rollout
from native_turn_accounting import account_turn
from native_host_controls import settings


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


class NativeApplicationSession:
    def __init__(self, registration, destination):
        self.registration = registration
        self.destination = Path(destination)
        self.destination.mkdir(parents=True, exist_ok=False)
        self.server = None
        self.opened = None
        self.closed = False
        self.phases = []

    def source_manifest(self):
        root = Path(self.registration['workspace']).resolve()
        excluded = self.registration.get('manifest_excludes')
        if not excluded:
            return manifest(root)
        excluded = set(excluded)
        result = {}
        for directory, folders, names in os.walk(root, followlinks=False):
            parent = Path(directory)
            folders[:] = [name for name in folders if (parent / name).relative_to(root).as_posix() not in excluded
                          and name not in ('__pycache__', '.git')]
            for name in names:
                path = parent / name
                key = path.relative_to(root).as_posix()
                if key not in excluded and path.suffix != '.pyc':
                    result[key] = file_hash(path)
        return result

    def open(self):
        reg = self.registration
        require(self.server is None and not self.closed, 'application_session_already_opened')
        work = Path(reg['workspace']).resolve()
        require(work.is_dir() and self.source_manifest() == reg['initial_manifest'], 'application_initial_source_changed')
        require(file_hash(reg['executable']) == reg['executable_sha256'], 'application_executable_changed')
        require(reg['model'] and reg['effort'], 'application_model_missing')
        save(self.destination / 'registration.json', reg)
        self.server = OwnedNativeRPC(reg['executable'], cwd=work, stderr_path=self.destination / 'stderr.txt',
            settings=settings(reg))
        try:
            initialized = self.server.call('initialize', {'clientInfo': {'name': 'wsc_application_study', 'version': '1'},
                'capabilities': {'experimentalApi': True}}, timeout=30)
            save(self.destination / 'initialized.json', initialized)
            self.server.send({'method': 'initialized'})
            sandbox = reg.get('sandbox', 'workspace-write')
            require(sandbox in {'workspace-write', 'read-only'}, 'application_sandbox_unregistered')
            self.opened = self.server.call('thread/start', {'cwd': str(work), 'model': reg['model'],
                'allowProviderModelFallback': False, 'approvalPolicy': 'never', 'sandbox': sandbox,
                'runtimeWorkspaceRoots': [str(work)], 'ephemeral': False, 'dynamicTools': []}, timeout=30)
            save(self.destination / 'thread-start.json', self.opened)
            require(self.opened['model'] == reg['model'] and self.opened['reasoningEffort'] == reg['effort'],
                    'application_native_model_mismatch')
            require(self.opened['approvalPolicy'] == 'never' and self.opened['sandbox']['type'] ==
                    ('workspaceWrite' if sandbox == 'workspace-write' else 'readOnly')
                    and Path(self.opened['cwd']).resolve() == work, 'application_native_execution_mismatch')
            fact = {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': json.dumps({
                'kind': 'experimental_execution_binding', 'current_workspace': str(work),
                'initial_manifest_sha256': digest(reg['initial_manifest']),
                'execution_mode': 'workspace_write' if sandbox == 'workspace-write' else 'read_only'}, ensure_ascii=False, sort_keys=True)}]}
            self.server.call('thread/inject_items', {'threadId': self.opened['thread']['id'], 'items': [fact]})
            save(self.destination / 'execution-fact.json', fact)
            path = Path(self.opened['thread']['path'])
            deadline = time.monotonic() + 3
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            snapshot = capture_rollout(path, archive=self.destination / 'opened.jsonl')
            require(snapshot.metadata['parse_complete'], 'application_open_history_incomplete')
            require(not any(row['type'] == 'token_usage_record' for row in snapshot.rows), 'application_unregistered_inference')
            return self.opened
        except BaseException:
            self.close()
            raise

    def execute_stage(self, request, destination, limits, record_phase, *, compact=False, output_schema=None):
        """Execute once, journal once. Limits are checked at response boundaries.

        The caller freezes study/arm cumulative budgets and boundary policy
        before invoking this method. It must not retry an incomplete stage.
        """
        require(self.server is not None and not self.closed and self.opened is not None, 'application_session_not_live')
        require(isinstance(request, str) and request.strip(), 'application_stage_request_missing')
        begin = time.monotonic()
        budget = PhaseBudget.resolve({'phase_budget': limits}, begin=begin, deadline=begin + limits['max_seconds'])
        area = Path(destination)
        area.mkdir(parents=True, exist_ok=False)
        tid = self.opened['thread']['id']
        path = Path(self.opened['thread']['path'])
        before = path.read_bytes()
        inherited = None
        if hasattr(self, 'fork_binding'):
            from native_recursive_fork import observe
            inherited = observe(before, self.fork_binding, allow_local_append=True)['inherited']
        save(area / 'attempt.json', dict(thread_id=tid, request=request, limits=limits,
            source_manifest=self.source_manifest(), before_sha256=sha256(before).hexdigest()))
        prior_ids = {row['payload']['response_id'] for row in records(path) if row['type'] == 'token_usage_record'}
        turn_id, terminal = None, False
        outcome = dict(thread_id=tid, completed=False, failure=None, finals=[], retry_notices=[])
        log = (area / 'events.jsonl').open('x', encoding='utf8')

        def observed(event):
            log.write(json.dumps(event, ensure_ascii=False) + '\n')
            log.flush()
            p = event.get('params', {})
            return p if p.get('threadId') in (None, tid) else None

        try:
            if compact:
                self.server.call('thread/compact/start', {'threadId': tid}, timeout=min(20, limits['max_seconds']))
            else:
                params = {'threadId': tid, 'model': self.registration['model'],
                    'effort': self.registration['effort'], 'input': [{'type': 'text', 'text': request}]}
                if output_schema is not None:
                    params['outputSchema'] = output_schema
                response = self.server.call('turn/start', params, timeout=min(20, limits['max_seconds']))
                turn_id = response['turn']['id']
            while time.monotonic() < budget.deadline:
                try:
                    event = self.server.event(timeout=min(.5, max(.01, budget.deadline-time.monotonic())))
                except queue.Empty:
                    continue
                p = observed(event)
                if p is None:
                    continue
                method = event.get('method')
                if compact and method == 'turn/started' and turn_id is None:
                    turn_id = p['turn']['id']
                if p.get('turnId') not in (None, turn_id):
                    continue
                require(not ('id' in event and method), 'application_unregistered_callback:' + str(method))
                if method == 'error':
                    outcome['retry_notices'].append(p)
                    raise RuntimeError('application_native_provider_error')
                if method == 'item/completed':
                    item = p.get('item', {})
                    if item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer':
                        outcome['finals'].append(item)
                if method == 'turn/completed' and p['turn']['id'] == turn_id:
                    terminal = True
                    outcome['completed'] = p['turn']['status'] == 'completed'
                    if not outcome['completed']:
                        outcome['failure'] = 'native_turn_' + p['turn']['status']
                    break
                if method == 'thread/tokenUsage/updated':
                    rows = [r for r in records(path) if r['type'] == 'token_usage_record'
                            and r['payload'].get('response_id') not in prior_ids]
                    reason = budget.stop_reason(usage(rows, tid), final=bool(outcome['finals']) or compact)
                    if reason:
                        outcome['failure'] = reason
                        break
            else:
                outcome['failure'] = 'registered_wall_cap'
        except Exception as error:
            outcome['failure'] = type(error).__name__ + ':' + str(error)
        finally:
            if not terminal and turn_id:
                try:
                    self.server.call('turn/interrupt', {'threadId': tid, 'turnId': turn_id}, timeout=8)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        try:
                            event = self.server.event(timeout=.25)
                        except queue.Empty:
                            continue
                        p = observed(event)
                        if p is not None and event.get('method') == 'turn/completed' and p['turn']['id'] == turn_id:
                            terminal = True
                            break
                except Exception as error:
                    outcome['interrupt_error'] = str(error)
            if not terminal:
                try:
                    outcome['termination'] = self.close()
                except Exception as error:
                    # Cleanup failure must not bypass receipt capture/journaling.
                    outcome['termination_error'] = type(error).__name__ + ':' + str(error)
            log.close()
            outcome['seconds'] = time.monotonic() - begin
            try:
                snapshot = capture_rollout(path, archive=area / 'rollout.jsonl')
                proof = account_turn(before, (area / 'rollout.jsonl').read_bytes(), thread_id=tid, turn_id=turn_id,
                                     inherited=inherited)
                outcome.update(receipts=proof['receipts'], turn_accounting=proof,
                    usage_complete=proof['complete'] and terminal and not outcome['retry_notices'],
                    rollout_snapshot=snapshot.metadata, rollout_sha256=snapshot.metadata['sha256'],
                    usage_completion_evidence=dict(complete=proof['complete'], reasons=proof['reasons'],
                        turn_id=turn_id, scope=proof['scope'], rollout_sha256=snapshot.metadata['sha256']),
                    compaction=compact)
                outcome['budget_observation'] = budget.observation(outcome['receipts'])
                if outcome['failure'] is None:
                    outcome['failure'] = budget.stop_reason(outcome['receipts'], final=True)
            except Exception as error:
                outcome.update(usage_complete=False, accounting_error=str(error))
            save(area / 'phase-outcome.json', outcome)
            record_phase(outcome)
            self.phases.append(outcome)
        return outcome

    def close(self):
        if self.closed:
            return self.server.owner.receipt if self.server else None
        self.closed = True
        if self.server:
            receipt = self.server.close()
            save(self.destination / 'process-cleanup.json', receipt)
            return receipt
