"""Opt-in stage runner for an already opened, explicitly mapped Linux session.

The caller supplies process-tree cleanup. This adapter neither starts a provider
nor grants capacity, and does not rewrite guest paths in native metadata.
"""
from pathlib import Path, PurePosixPath

from native_application_session import NativeApplicationSession, require
from wsc.evidence import link_like


class MappedContextSession(NativeApplicationSession):
    def __init__(self, registration, destination, *, server, opened, actor_root, cleanup):
        require(callable(cleanup), 'context_session_cleanup_missing')
        require(all(type(registration.get(k)) is str and bool(registration[k]) for k in ('model', 'effort'))
                and type(opened.get('thread', {}).get('id')) is str and bool(opened['thread']['id']),
                'context_session_registration_invalid')
        require(registration.get('workspace') == '/work/actor'
                and opened.get('cwd') == '/work/actor', 'context_session_workspace_invalid')
        require(opened.get('model') == registration.get('model')
                and opened.get('reasoningEffort') == registration.get('effort'),
                'context_session_model_changed')
        self.actor_root = Path(actor_root).absolute()
        self._cleanup = cleanup
        self._cleanup_receipt = None
        self._server = server
        self._owner = opened['thread']['id']
        self._guest_history = opened['thread']['path']
        super().__init__(registration, destination)
        self.server, self.opened = server, opened
        work, history = self.workspace_path(), self.rollout_path()
        from native_evidence import save
        save(self.destination / 'registration.json', registration)
        save(self.destination / 'thread-start.json', opened)
        save(self.destination / 'host-paths.json', dict(host_workspace=str(work), host_history=str(history),
            guest_workspace='/work/actor', guest_history=self._guest_history,
            scope='Explicit host path mapping; no provider or request-capacity admission'))

    def open(self):
        raise ValueError('context_session_already_opened')

    def _root(self):
        require(not self.closed, 'context_session_closed')
        for part in (self.actor_root, *self.actor_root.parents):
            require(not link_like(part), 'context_session_path_link')
        root = self.actor_root.resolve(strict=True)
        require(self.opened['thread']['id'] == self._owner
                and self.server is self._server
                and self.opened.get('cwd') == '/work/actor'
                and self.registration.get('workspace') == '/work/actor',
                'context_session_owner_changed')
        proc = getattr(self.server, 'proc', None)
        require(proc is None or proc.poll() is None, 'context_session_not_live')
        require(self.opened.get('model') == self.registration.get('model')
                and self.opened.get('reasoningEffort') == self.registration.get('effort'),
                'context_session_model_changed')
        return root

    def _mapped(self, relative, *, file):
        path = self._root()
        for name in relative.parts:
            path = path / name
            require(not link_like(path), 'context_session_path_link')
        value = path.resolve(strict=True)
        require(value.is_relative_to(self.actor_root.resolve(strict=True))
                and (value.is_file() if file else value.is_dir()), 'context_session_path_invalid')
        return value

    def workspace_path(self):
        return self._mapped(PurePosixPath('actor'), file=False)

    def rollout_path(self):
        raw = self.opened['thread']['path']
        require(type(raw) is str and raw == self._guest_history and '\\' not in raw,
                'context_session_history_changed')
        guest = PurePosixPath(raw)
        prefix = PurePosixPath('/work/home/.codex/sessions')
        require('..' not in guest.parts and guest.is_relative_to(prefix)
                and guest != prefix and guest.suffix == '.jsonl', 'context_session_history_outside_home')
        return self._mapped(guest.relative_to('/work'), file=True)

    def close(self):
        if self.closed:
            return self._cleanup_receipt
        # Mark closed only after cleanup succeeds, allowing cleanup retry on error.
        receipt = self._cleanup(self.server)
        self._cleanup_receipt = receipt
        self.closed = True
        from native_evidence import save
        save(self.destination / 'process-cleanup.json', receipt)
        return receipt
