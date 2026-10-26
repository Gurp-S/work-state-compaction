"""Native application session opened through a registered parent fork."""
from pathlib import Path

from native_application_session import NativeApplicationSession, require
from native_owned_process import OwnedNativeRPC
from native_recursive_fork import seal, observe, metadata
from native_evidence import save, file_hash, manifest, import_evidence
from native_rollout_snapshot import capture_rollout, parse_rollout
from native_host_controls import settings
from native_fork_policy import execution_mode


class NativeForkSession(NativeApplicationSession):
    def open(self):
        reg = self.registration
        sandbox, sandbox_kind = execution_mode(reg)
        require(self.server is None and not self.closed, 'application_session_already_opened')
        require(self.source_manifest() == reg['initial_manifest'], 'application_fork_source_changed')
        require(file_hash(reg['executable']) == reg['executable_sha256'], 'application_executable_changed')
        save(self.destination / 'registration.json', reg)
        self.server = OwnedNativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=self.destination / 'stderr.txt',
            settings=settings(reg))
        try:
            initialized = self.server.call('initialize', {'clientInfo': {'name': 'wsc_application_study', 'version': '1'},
                'capabilities': {'experimentalApi': True}})
            save(self.destination / 'initialized.json', initialized)
            self.server.send({'method': 'initialized'})
            params = dict(threadId=reg['parent_thread_id'], cwd=reg['workspace'], model=reg['model'],
                approvalPolicy='never', sandbox=sandbox, runtimeWorkspaceRoots=[reg['workspace']],
                ephemeral=False, excludeTurns=True, deferGoalContinuation=True)
            if reg.get('before_turn_id'):
                params['beforeTurnId'] = reg['before_turn_id']
            self.opened = self.server.call('thread/fork', params, timeout=35)
            save(self.destination / 'thread-fork.json', self.opened)
            require(self.opened['model'] == reg['model'] and self.opened['reasoningEffort'] == reg['effort'],
                    'application_native_model_mismatch')
            require(self.opened['sandbox']['type'] == sandbox_kind and self.opened['approvalPolicy'] == 'never'
                    and Path(self.opened['cwd']).resolve() == Path(reg['workspace']).resolve(),
                    'application_fork_configuration_mismatch')
            snap = capture_rollout(self.opened['thread']['path'], archive=self.destination / 'opened.jsonl')
            self.fork_binding = seal((self.destination / 'opened.jsonl').read_bytes(), reg['parent_paths'], self.destination / 'ancestry')
            observed = observe((self.destination / 'opened.jsonl').read_bytes(), self.fork_binding)
            require(not any(row['type'] == 'token_usage_record' for row in snap.rows), 'application_fork_unregistered_inference')
            save(self.destination / 'fork-admission.json', observed['evidence'])
            return self.opened
        except BaseException:
            self.close()
            raise

    def inject(self, items):
        require(self.server is not None and not self.closed and isinstance(items, list) and items, 'application_import_not_live')
        path = Path(self.opened['thread']['path'])
        before = path.read_bytes()
        result = self.server.call('thread/inject_items', {'threadId': self.opened['thread']['id'], 'items': items})
        after = path.read_bytes()
        require(after.startswith(before), 'application_import_source_prefix_changed')
        delta = parse_rollout(after[len(before):])
        require(delta.metadata['parse_complete'] and not any(r['type'] == 'token_usage_record' for r in delta.rows),
                'application_import_unregistered_inference')
        local_items = [r['payload'] for r in delta.rows if r['type'] == 'response_item']
        proof = import_evidence(local_items, items)
        require(proof['matched'] and len(local_items) == len(items), 'application_import_items_not_exact')
        save(self.destination / 'import-result.json', dict(native=result, evidence=proof))
        capture_rollout(path, archive=self.destination / 'after-import.jsonl')
        return proof
