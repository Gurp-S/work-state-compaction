"""Opt-in typed scope facts for selection; no semantic relevance decisions."""
from datetime import datetime, timezone
from pathlib import Path
import re

from native_evidence import read, save, file_hash, manifest, digest

KIND = 'a3_scoped_selection_state_v1'
ALGORITHM = 'sha256_canonical_file_manifest_v1'


def binding(scope, value):
    return dict(scope=scope, algorithm=ALGORITHM, sha256=digest(value), entries=len(value))


def compare(left, right):
    for value in (left, right):
        if (not isinstance(value.get('scope'), str) or not value['scope']
                or not isinstance(value.get('algorithm'), str) or not value['algorithm']
                or not isinstance(value.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])):
            raise ValueError('source_scope_binding_invalid')
    if left['scope'] != right['scope']:
        return dict(status='different_scopes', equal=None)
    if left['algorithm'] != right['algorithm']:
        return dict(status='different_algorithms', equal=None)
    same = left['sha256'] == right['sha256']
    return dict(status='same_content' if same else 'different_content', equal=same)


def build(snapshot, registration_path, grade_path, expected_checks, next_stage):
    snapshot = Path(snapshot)
    registration, grade = read(registration_path), read(grade_path)
    workspace = binding('registered_workspace_manifest', manifest(snapshot))
    current_gui = binding('gui/src', manifest(snapshot / 'gui/src'))
    observed_gui = binding('gui/src', registration['source_manifest'])
    if grade['source_manifest_sha256'] != observed_gui['sha256']:
        raise ValueError('grade_manifest_scope_binding_changed')
    checks = grade['observations']
    if (len(checks) != len(expected_checks) or {row['id'] for row in checks} != set(expected_checks)
            or any(type(row['passed']) is not bool for row in checks)):
        raise ValueError('grade_scope_incomplete')
    return dict(kind=KIND, binding_checked_at=datetime.now(timezone.utc).isoformat(),
        source_snapshot=str(snapshot), workspace_binding=workspace, gui_source_binding=current_gui,
        original_S2_receipt=dict(source_binding=observed_gui, observed_at=grade['observed_at'], checks=checks,
            registration=dict(path=str(registration_path), sha256=file_hash(registration_path)),
            grade=dict(path=str(grade_path), sha256=file_hash(grade_path)),
            auxiliary=dict(package_sha256=registration['package_sha256'], lock_sha256=registration['lock_sha256'])),
        receipt_to_snapshot_gui=compare(observed_gui, current_gui),
        workspace_to_gui=compare(workspace, current_gui),
        auxiliary_to_snapshot=dict(package_matches=registration['package_sha256'] == file_hash(snapshot / 'gui/package.json'),
            lock_matches=registration['lock_sha256'] == file_hash(snapshot / 'gui/package-lock.json')),
        original_S2_native_turn_completed=False, visual_coverage='not_attested_by_this_automatic_receipt',
        source_stage='S2', requested_delivery_stage=next_stage['id'], requested_delivery_text=next_stage['request'])


def load(reference, *, receiving_workspace=None):
    if file_hash(reference['path']) != reference['sha256']:
        raise ValueError('scoped_selection_state_changed')
    value = read(reference['path'])
    if value.get('kind') != KIND:
        raise ValueError('scoped_selection_state_kind_invalid')
    current = binding('gui/src', manifest(Path(value['source_snapshot']) / 'gui/src'))
    workspace = binding('registered_workspace_manifest', manifest(value['source_snapshot']))
    if current != value['gui_source_binding'] or workspace != value['workspace_binding']:
        raise ValueError('scoped_selection_snapshot_changed')
    if receiving_workspace is not None:
        receiving = binding('gui/src', manifest(Path(receiving_workspace) / 'gui/src'))
        if receiving != value['gui_source_binding']:
            raise ValueError('scoped_selection_receiving_source_changed')
    for key in ('registration', 'grade'):
        item = value['original_S2_receipt'][key]
        if file_hash(item['path']) != item['sha256']:
            raise ValueError('scoped_selection_receipt_changed')
    return value


def as_event(value):
    from wsc.contracts import Event, encode
    return Event('scoped-selection-state:' + digest(value), 'observation', value,
        text=encode(value), observed_at=value['binding_checked_at'])
