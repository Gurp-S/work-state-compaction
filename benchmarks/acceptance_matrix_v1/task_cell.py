"""Explicit task-bound sidecar. Original Cell and BaselineCell retain T1 defaults."""
from pathlib import Path
from .acceptors import accept_t1, accept_t3, load_candidate
from .paired_cell import Cell
from .baseline_cell import BaselineCell


TASKS = {'T1': ('retry_client.py', accept_t1), 'T3': ('migrate.py', accept_t3)}


class TaskBinding:
    def __init__(self, name, plan, out, ledger, inputs, *, task_id, **kwargs):
        if task_id not in TASKS or plan.get('task_id') != task_id or inputs.get('task') != task_id:
            raise ValueError('matrix_task_binding_mismatch')
        policy=plan.get('task_evaluator_policy')
        if policy is not None and (task_id!='T3' or policy!='implementation_neutral_t3_v2'):
            raise ValueError('matrix_task_evaluator_policy_unregistered')
        self.task_id = task_id
        self.task_evaluator_policy=policy
        super().__init__(name, plan, out, ledger, inputs, **kwargs)

    def evaluate_artifact(self):
        filename, accept = TASKS[self.task_id]
        if self.task_evaluator_policy=='implementation_neutral_t3_v2':
            from .acceptor_t3_v2 import accept_t3_v2
            accept=accept_t3_v2
        path = self.work / filename
        # Reject a link to another task/private artifact before importing candidate code.
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('matrix_candidate_link_not_allowed')
        if not path.resolve(strict=True).is_relative_to(self.work.resolve(strict=True)):
            raise ValueError('matrix_candidate_outside_workspace')
        return accept(load_candidate(path))


class TaskCell(TaskBinding, Cell):
    pass


class TaskBaselineCell(TaskBinding, BaselineCell):
    pass
