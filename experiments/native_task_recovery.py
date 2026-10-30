"""Opt-in ordinary receiver wiring; no compaction policy or capacity estimate.

The factory has the existing fresh(dynamic_tools=..., selector_runtime=...)
contract. Creating a real receiver is an explicit caller action. This module
is not imported by existing runners and does not authorize experiments.
"""
from copy import deepcopy
from pathlib import Path

from wsc.contracts import require
from wsc.source_access import SnapshotSourceAccess
from native_source_tool import SOURCE_TOOL
from native_source_tool_budget import BudgetResultSourceToolHandler


class _TaskHandler(BudgetResultSourceToolHandler):
    def __init__(self, receiver, reader):
        super().__init__(reader)
        self.receiver = receiver

    def handle(self, event, *, thread_id, turn_id):
        # Reuse the reader's reentrant lock for handler cache and budget state.
        with self.reader.lock:
            self.receiver._require_live()
            require(thread_id == self.receiver.owner, 'task_source_owner_changed')
            return super().handle(event, thread_id=thread_id, turn_id=turn_id)


class TaskReceiver:
    def __init__(self, session, reader):
        self.session = session
        opened = session.opened or {}
        self.owner = opened.get('thread', {}).get('id')
        require(type(self.owner) is str and bool(self.owner), 'task_source_owner_missing')
        self.workspace = str(Path(session.registration['workspace']).resolve())
        require(self.workspace == reader.store.workspace, 'task_source_workspace_mismatch')
        self._require_live()
        self.handler = _TaskHandler(self, reader)

    def _require_live(self):
        require(self.session.server is not None and not self.session.closed
                and self.session.opened is not None, 'task_source_session_not_live')
        require(self.session.opened['thread']['id'] == self.owner
                and str(Path(self.session.registration['workspace']).resolve()) == self.workspace,
                'task_source_owner_changed')

    def execute_stage(self, request, destination, limits, record_phase, *,
                      output_schema=None, capacity_check=None, system_admission=None):
        self._require_live()
        # Capacity belongs to the actual host request. This port has neither
        # that request's tokenization nor a valid native output reserve.
        if system_admission is None:
            require(callable(capacity_check), 'task_source_capacity_unverified')
            require(capacity_check(self.session, request, output_schema) is True,
                    'task_source_capacity_not_admitted')
        else:
            require(capacity_check is None, 'task_source_admission_modes_conflict')
            from native_system_task_admission import admit
            self.last_system_admission = admit(self, request, output_schema, system_admission)
        self._require_live()
        return self.session.execute_stage(request, destination, limits, record_phase,
            output_schema=output_schema, tool_handler=self.handler)

    def close(self):
        return self.session.close()


def open_task_receiver(open_session, reader):
    """Register and dispatch the same source port, using the ordinary runtime.

open_session is typically a partial of the existing fresh factory. A factory
failure owns its cleanup; a post-open binding failure closes the returned
session. No source text or answer is prefetched here.
    """
    require(isinstance(reader, SnapshotSourceAccess), 'task_source_reader_invalid')
    definition = deepcopy(SOURCE_TOOL)
    definition['description'] += f" Bound historical source prefix cut: {reader.snapshot_binding['cut']}."
    session = open_session(dynamic_tools=[definition], selector_runtime=None)
    try:
        return TaskReceiver(session, reader)
    except BaseException:
        session.close()
        raise
