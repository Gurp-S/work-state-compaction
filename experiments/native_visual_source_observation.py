"""Source-bound facts from one completed browser geometry observation."""
from datetime import datetime, timezone
from pathlib import Path

from native_evidence import read, file_hash, manifest
from native_scoped_selection_state import binding


def from_probe(gui, registration_path, result_path):
    registration, result = read(registration_path), read(result_path)
    current = manifest(Path(gui) / 'src')
    if registration['source_manifest'] != current or result.get('source_unchanged') is not True:
        raise ValueError('visual_observation_source_changed')
    if (registration['package_sha256'] != file_hash(Path(gui) / 'package.json')
            or registration['lock_sha256'] != file_hash(Path(gui) / 'package-lock.json')):
        raise ValueError('visual_observation_auxiliary_changed')
    if result.get('check_executed') is not True or result.get('errors') != []:
        raise ValueError('visual_observation_not_completed')
    for field in ('clipping_observed', 'hasUserScrollableAncestor', 'hasClippingAncestor', 'changedScroll'):
        if type(result.get(field)) is not bool:
            raise ValueError('visual_observation_result_unknown')
    recorded = datetime.fromtimestamp(Path(result_path).stat().st_mtime, timezone.utc).isoformat()
    return dict(kind='source_bound_visual_observation_v1', source_binding=binding('gui/src', current),
        receipt_file_mtime_utc=recorded, observation_time_basis='receipt_file_mtime',
        scenario=registration['scenario'], viewport=registration['viewport'],
        clipping_observed=result['clipping_observed'], report_height=result['initial']['reportHeight'],
        viewport_height=result['initial']['viewportHeight'], user_scrollable_ancestor=result['hasUserScrollableAncestor'],
        clipping_ancestor=result['hasClippingAncestor'], real_wheel_changed_scroll=result['changedScroll'],
        browser=result['browser'], full_visual_qualification=False,
        registration=dict(path=str(registration_path), sha256=file_hash(registration_path)),
        result=dict(path=str(result_path), sha256=file_hash(result_path)))


def as_event(value):
    from wsc.contracts import Event, encode, digest
    return Event('visual-source-observation:' + digest(value), 'observation', value,
        text=encode(value), observed_at=value['receipt_file_mtime_utc'])
