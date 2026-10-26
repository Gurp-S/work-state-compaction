"""Opt-in host-bound publication of unchanged task messages and cold bootstrap.

The source admission binds only an initial native prefix. Later controls remain
task history. A current host is observed before publication, never inferred from
launch options. Publication and native import do not imply a HostReceipt.
"""
from copy import deepcopy
import json
from pathlib import Path

from native_evidence import digest, file_hash, import_evidence, read, save
from native_rollout_snapshot import capture_rollout
from native_message_checkpoint import prepare_message_checkpoint
from native_pair_admission import observe
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.contracts import encode, require


def normalized(item):
    return {k: item[k] for k in ('type', 'role', 'content') if k in item}


def admitted_prefix(snapshot, admission, controls, *, thread_id, fresh=False):
    require(snapshot.metadata['parse_complete'], 'host_archive_incomplete')
    metas = [r['payload'] for r in snapshot.rows if r['type'] == 'session_meta']
    require(len(metas) == 1 and metas[0].get('id') == thread_id
            and admission['thread_id'] == thread_id and admission['response_count'] == 0,
            'host_admission_identity_mismatch')
    require(digest(metas[0].get('base_instructions')) == admission['host']['base_instructions_sha256'],
            'host_base_observation_changed')
    require(controls and digest(controls) == admission['controls_sha256'], 'host_control_binding_changed')
    items = [r['payload'] for r in snapshot.rows if r['type'] == 'response_item']
    matches = [i for i in range(len(items) - len(controls) + 1)
               if import_evidence(items[i:i + len(controls)], controls)['matched']]
    require(len(matches) == 1, 'host_execution_boundary_missing_or_ambiguous')
    start = matches[0]
    prefix = items[:start]
    require(prefix and digest(prefix) == admission['prefix_sha256'], 'host_prefix_changed')
    require([normalized(p) for p in prefix] == admission['host']['bootstrap_messages'],
            'host_bootstrap_observation_changed')
    require(all(p.get('type') == 'message' and p.get('role') in {'system', 'developer', 'user'}
                for p in prefix), 'host_bootstrap_contains_task_activity')
    # A fabricated zero in an admission cannot hide an actual earlier response.
    seen = 0
    for row in snapshot.rows:
        if row['type'] == 'response_item':
            if seen == start:
                break
            seen += 1
        require(row['type'] not in {'token_usage_record', 'compacted'}, 'host_prior_inference')
    if fresh:
        require(len(items) == start + len(controls)
                and not any(r['type'] in {'token_usage_record', 'compacted'}
                            or (r['type'] == 'event_msg' and r.get('payload', {}).get('type') == 'task_started')
                            for r in snapshot.rows),
                'host_target_not_fresh')
    return deepcopy(prefix)


class HostContextAdapter(RecordedCodexCheckpointAdapter):
    def __init__(self, source_snapshot, admission, registration, phase, target_snapshot, target_admission, marker):
        require(registration['accounting_scope'] == 'fresh_single_turn', 'host_source_scope_unsupported')
        require(source_snapshot.metadata['sha256'] == phase['rollout_sha256'], 'host_source_archive_changed')
        prefix = admitted_prefix(source_snapshot, admission, [registration['execution_fact']],
                                 thread_id=phase['thread_id'])
        self.bind_prefix(source_snapshot, prefix, registration['workspace'], phase['thread_id'],
                         {'source_admission_sha256': digest(admission),
                          'source_registration_sha256': digest(registration)},
                         target_snapshot, target_admission, marker)

    def bind_prefix(self, source_snapshot, prefix, workspace, thread_id, source_proof,
                    target_snapshot, target_admission, marker):
        self.prefix = deepcopy(prefix)
        current = admitted_prefix(target_snapshot, target_admission, marker,
                                   thread_id=target_admission['thread_id'], fresh=True)
        users = iter(normalized(p) for p in current if p['role'] == 'user')
        require(all(any(candidate == normalized(p) for candidate in users)
                    for p in self.prefix if p['role'] == 'user'), 'host_user_control_coverage_missing')
        self.keys = [f"native:{thread_id}:{i}:{digest(p)}" for i, p in enumerate(self.prefix)]
        self.workspace = str(Path(workspace).resolve())
        self.proof = {'source_rollout_sha256': source_snapshot.metadata['sha256'],
                      **deepcopy(source_proof),
                      'source_bootstrap_sha256': digest(self.prefix),
                      'source_ids': self.keys,
                      'target_thread_id': target_admission['thread_id'],
                      'target_observation_sha256': target_snapshot.metadata['sha256'],
                      'target_admission_sha256': digest(target_admission),
                      'target_bootstrap_sha256': digest(current)}

    def capabilities(self):
        return {**super().capabilities(), 'adapter': 'codex_host_context_checkpoint_v1',
                'host_context_binding': deepcopy(self.proof), 'semantic_status': 'unverified'}

    def validate_binding(self, binding):
        require(str(Path(binding['workspace']).resolve()) == self.workspace, 'host_source_workspace_mismatch')

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        items = super().render(body, sources, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        require(items[:len(self.prefix)] == self.prefix, 'host_checkpoint_prefix_changed')
        by_id = {row['id']: row for row in sources}
        for key, original in zip(self.keys, self.prefix):
            require(key in by_id and by_id[key]['payload'] == original, 'host_source_identity_changed')
            loc = locators[key]
            require(file_hash(loc['file_path']) == loc['sha256'] and read(loc['file_path']) == original,
                    'host_cold_evidence_changed')
        # The structural position is supplied by the renderer contract, not a
        # search for JSON text that a task message may itself happen to contain.
        state_index = sum(row['kind'] == 'message' for row in body['sources'])
        state = json.loads(items[state_index]['content'][0]['text'])
        require(state.get('kind') == 'working_state' and 'historical_host_context' not in state,
                'host_state_shape_invalid')
        state['historical_host_context'] = {'kind': 'archived_native_startup_observation', 'sources': [
            {'source_id': key, 'path': locators[key]['file_path'], 'sha256': locators[key]['sha256'],
             'observed_at': locators[key]['observed_at']} for key in self.keys]}
        items[state_index]['content'][0]['text'] = encode(state)
        return items[len(self.prefix):]


class PendingHostCheckpoint:
    """Defer publication until the receiver's real bootstrap is available."""
    def __init__(self, area, workspace, source_rollout, source_phase, acceptance, receipt_path, source_cell,
                 *, bind_receipt_file=False):
        self.bind_receipt_file = bind_receipt_file
        self.area, self.workspace = Path(area), workspace
        self.source_rollout, self.phase = Path(source_rollout), deepcopy(source_phase)
        self.acceptance, self.receipt_path = deepcopy(acceptance), receipt_path
        self.admission = read(Path(source_cell) / 'admission.json')
        self.registration = read(Path(source_cell) / 'registration.json')
        self.snapshot = capture_rollout(source_rollout)
        require(self.snapshot.metadata['sha256'] == self.phase['rollout_sha256'], 'host_source_archive_changed')

    def adapter_for(self, target, admission, marker):
        return HostContextAdapter(self.snapshot, self.admission, self.registration, self.phase,
                                  target, admission, marker)

    def import_into(self, server, opened, cell, fact):
        from run_native_pair import import_items
        cell = Path(cell)
        host_cell = cell / 'host-observation'
        host_cell.mkdir()
        marker = [{'type': 'message', 'role': 'assistant', 'phase': 'commentary',
                   'content': [{'type': 'output_text', 'text': encode({
                       'kind': 'checkpoint_host_observation', 'task_execution': 'not_started',
                       'source_rollout_sha256': self.snapshot.metadata['sha256']})}]}]
        import_items(server, opened, marker, host_cell)
        admission = observe(opened, marker)
        save(host_cell / 'admission.json', admission)
        target = capture_rollout(opened['thread']['path'], archive=host_cell / 'rollout.jsonl')
        adapter = self.adapter_for(target, admission, marker)
        save(host_cell / 'binding.json', adapter.proof)
        package = prepare_message_checkpoint(self.area, self.workspace, self.source_rollout, self.phase,
                                             self.acceptance, self.receipt_path, adapter=adapter,
                                             bind_receipt_file=self.bind_receipt_file)
        require(file_hash(opened['thread']['path']) == target.metadata['sha256'], 'host_target_changed_before_import')
        require(file_hash(self.source_rollout) == self.snapshot.metadata['sha256'], 'host_source_changed_before_import')
        if hasattr(adapter, 'validate_dependencies'):
            adapter.validate_dependencies()
        items = [*package['items'], fact]
        import_items(server, opened, items, cell)
        save(cell / 'host-publication.json', {'package_digest': package['package_digest'],
             'operation_id': package['operation_id'], 'items_sha256': digest(items),
             'host_binding': adapter.proof, 'installation_receipt': None,
             'scope': 'Native import accepted and observed; no atomic installation or semantic qualification.'})
        return items
