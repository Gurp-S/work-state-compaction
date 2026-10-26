"""Explicit execution applicability for opt-in visual observations.

Historical source-only observations are not upgraded by this module. A context
is captured before a new execution and verified against the receiving context.
"""
from pathlib import Path

from native_evidence import read, file_hash, manifest, digest
from native_scoped_selection_state import binding
from native_visual_source_observation import from_probe

KIND = 'visual_execution_context_v2'
ENTRIES = {'inner_body': 'UsagePageBody', 'production_panel': 'A3SnapshotPanel'}


def capture(gui, fixture, probe, *, entry, scenario, viewport):
    gui, fixture = Path(gui), Path(fixture)
    if entry not in ENTRIES:
        raise ValueError('evaluation_context_entry_unknown')
    expected = ENTRIES[entry]
    main = (fixture / 'harness/main.tsx').read_text(encoding='utf8')
    if (f'import {{{expected}}}' not in main or f'<{expected} active />' not in main):
        raise ValueError('evaluation_context_entry_mismatch')
    if (not isinstance(scenario, str) or not scenario or set(viewport) != {'width', 'height'}
            or any(type(v) is not int or v <= 0 for v in viewport.values())):
        raise ValueError('evaluation_context_scenario_invalid')
    # Provenance descriptors contain private absolute paths; executable fixture
    # identity is independent of relocation, while all harness/contract bytes count.
    host_files = {k: v for k, v in manifest(fixture).items()
        if k not in ('evaluation-host-binding.json', 'transport-binding.json')}
    return dict(kind=KIND, gui=binding('gui/src', manifest(gui / 'src')),
        package_sha256=file_hash(gui / 'package.json'), lock_sha256=file_hash(gui / 'package-lock.json'),
        host=binding('evaluation_fixture_execution_files', host_files), entry=entry,
        probe_sha256=file_hash(probe), scenario=scenario, viewport=dict(viewport))


def match(recorded, receiving):
    if recorded.get('kind') != KIND or receiving.get('kind') != KIND:
        raise ValueError('evaluation_context_binding_missing')
    return dict(equal=recorded == receiving,
        status='same_execution_context' if recorded == receiving else 'different_execution_context')


def from_bound_probe(gui, fixture, probe, context_registration, registration_path, result_path):
    recorded = read(context_registration)
    if recorded.get('kind') != KIND:
        raise ValueError('evaluation_context_binding_missing')
    receiving_context = capture(gui, fixture, probe, entry=recorded['entry'],
        scenario=recorded['scenario'], viewport=recorded['viewport'])
    if not match(recorded, receiving_context)['equal']:
        raise ValueError('visual_observation_execution_context_changed')
    if Path(context_registration).stat().st_mtime_ns > min(
            Path(registration_path).stat().st_mtime_ns, Path(result_path).stat().st_mtime_ns):
        raise ValueError('visual_observation_context_registered_after_probe')
    registration = read(registration_path)
    if (registration['scenario'] != recorded['scenario'] or registration['viewport'] != recorded['viewport']
            or binding('gui/src', registration['source_manifest']) != recorded['gui']
            or registration['package_sha256'] != recorded['package_sha256']
            or registration['lock_sha256'] != recorded['lock_sha256']):
        raise ValueError('visual_observation_probe_context_mismatch')
    value = from_probe(gui, registration_path, result_path)
    return {**value, 'kind': 'execution_bound_visual_observation_v1',
        'execution_context': recorded, 'execution_context_sha256': digest(recorded),
        'context_registration': dict(path=str(context_registration), sha256=file_hash(context_registration)),
        'applicability': 'Recorded component entry, fixture, source, probe, scenario and viewport only'}
