"""Explicit execution mode for optional native read-only review forks."""


def execution_mode(registration):
    mode = registration.get('sandbox', 'workspace-write')
    if mode not in ('workspace-write', 'read-only'):
        raise ValueError('application_fork_sandbox_unregistered')
    return mode, 'readOnly' if mode == 'read-only' else 'workspaceWrite'
