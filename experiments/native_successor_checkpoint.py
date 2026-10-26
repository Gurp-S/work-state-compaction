"""Opt-in repeated checkpoints: immutable host origin and registered cold ancestry.

Origin is a zero-inference native observation, independent of the later phase's
accounting. Ancestry comes from registered publication receipts, never from paths
guessed out of model-authored text. This module does not classify evidence truth.
"""
from copy import deepcopy
from pathlib import Path

from native_evidence import read, digest, file_hash, import_evidence
from native_rollout_snapshot import capture_rollout
from native_host_checkpoint import HostContextAdapter, PendingHostCheckpoint, admitted_prefix
from wsc.contracts import require


def host_origin(rollout, admission, controls):
    snapshot = capture_rollout(rollout)
    admitted_prefix(snapshot, admission, controls, thread_id=admission['thread_id'], fresh=True)
    return {'rollout': str(Path(rollout).resolve()), 'sha256': snapshot.metadata['sha256'],
            'admission': deepcopy(admission), 'controls': deepcopy(controls)}


def origin_prefix(origin, source_snapshot, phase):
    snapshot = capture_rollout(origin['rollout'])
    require(snapshot.metadata['sha256'] == origin['sha256'], 'successor_origin_changed')
    prefix = admitted_prefix(snapshot, origin['admission'], origin['controls'],
                             thread_id=phase['thread_id'], fresh=True)
    require(source_snapshot.metadata['parse_complete'] and
            source_snapshot.metadata['sha256'] == phase['rollout_sha256'], 'successor_source_changed')
    require(source_snapshot.rows[:len(snapshot.rows)] == snapshot.rows, 'successor_origin_history_changed')
    # Revalidate against the completed source, including identity and unique
    # boundary. A later task control that happens to repeat text is not retired.
    actual = admitted_prefix(source_snapshot, origin['admission'], origin['controls'],
                             thread_id=phase['thread_id'])
    require(actual == prefix, 'successor_origin_prefix_changed')
    return prefix


def package_evidence(path, expected_digest):
    path = Path(path).resolve()
    package = read(path)
    require(package['package_digest'] == expected_digest and
            digest({k:v for k,v in package.items() if k != 'package_digest'}) == expected_digest,
            'successor_parent_package_changed')
    files = {str(path): file_hash(path)}
    def bound_file(location, expected):
        location = str(Path(location).resolve())
        require(location not in files or files[location] == expected, 'successor_dependency_conflict')
        require(file_hash(location) == expected, 'successor_cold_evidence_changed')
        files[location] = expected
    for name in ('source_index','understanding_index'):
        require(digest(read(package[name])) == package[name+'_sha256'], 'successor_index_changed')
        bound_file(package[name], file_hash(package[name]))
    require(read(package['source_index']) == package['evidence'], 'successor_index_evidence_mismatch')
    for locator in [*package['evidence'].values(), *package.get('excerpt_evidence',{}).values()]:
        bound_file(locator['file_path'], locator['sha256'])
        if 'readable_path' in locator:
            bound_file(locator['readable_path'], locator['readable_sha256'])
    return package, files


class SuccessorHostAdapter(HostContextAdapter):
    def __init__(self, source_snapshot, phase, workspace, origin, parent_path, parent_digest,
                 target_snapshot, target_admission, marker):
        prefix = origin_prefix(origin, source_snapshot, phase)
        parent, files = package_evidence(parent_path, parent_digest)
        require(parent.get('adapter',{}).get('host_context_binding',{}).get('target_thread_id') == phase['thread_id'],
                'successor_parent_receiver_changed')
        # The immediate registered parent must actually occur in this thread.
        items = [r['payload'] for r in source_snapshot.rows if r['type'] == 'response_item']
        imported = import_evidence(items, parent['items'])
        require(parent['items'] and imported['matched'], 'successor_parent_not_in_source')
        require(Path(parent['binding']['workspace']).resolve() == Path(workspace).resolve(),
                'successor_parent_workspace_changed')
        self.ancestors = deepcopy(parent.get('adapter',{}).get('ancestor_packages',[]))
        self.ancestors.append({'path':str(Path(parent_path).resolve()), 'package_digest':parent_digest})
        require(len({p['path'] for p in self.ancestors}) == len(self.ancestors), 'successor_ancestry_cycle')
        for ancestor in self.ancestors[:-1]:
            _, inherited = package_evidence(ancestor['path'], ancestor['package_digest'])
            require(all(p not in files or files[p] == h for p,h in inherited.items()),
                    'successor_dependency_conflict')
            files.update(inherited)
        self.dependencies = files
        self.bind_prefix(source_snapshot, prefix, workspace, phase['thread_id'],
            {'source_origin_sha256':digest(origin), 'source_phase_sha256':digest(phase),
             'parent_package_digest':parent_digest, 'parent_import':imported,
             'cold_dependency_manifest_sha256':digest(files)}, target_snapshot, target_admission, marker)

    def capabilities(self):
        return {**super().capabilities(), 'adapter':'codex_successor_host_checkpoint_v1',
                'ancestor_packages':deepcopy(self.ancestors),
                'cold_dependency_manifest_sha256':digest(self.dependencies)}

    def validate_dependencies(self):
        require(all(file_hash(p) == h for p,h in self.dependencies.items()), 'successor_dependency_changed')

    def render(self, *args, **kwargs):
        self.validate_dependencies()
        return super().render(*args, **kwargs)


class PendingSuccessorCheckpoint(PendingHostCheckpoint):
    def __init__(self, area, workspace, source_rollout, source_phase, acceptance, receipt_path,
                 *, origin, parent_path, parent_digest, bind_receipt_file=False):
        self.bind_receipt_file = bind_receipt_file
        self.area, self.workspace = Path(area), workspace
        self.source_rollout, self.phase = Path(source_rollout), deepcopy(source_phase)
        self.acceptance, self.receipt_path = deepcopy(acceptance), receipt_path
        self.origin = deepcopy(origin)
        self.parent_path, self.parent_digest = Path(parent_path), parent_digest
        self.snapshot = capture_rollout(source_rollout)
        origin_prefix(self.origin, self.snapshot, self.phase)

    def adapter_for(self, target, admission, marker):
        return SuccessorHostAdapter(self.snapshot, self.phase, self.workspace, self.origin,
            self.parent_path, self.parent_digest, target, admission, marker)
