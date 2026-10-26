"""Native admission of both opt-in fixtures and source-bound C review receipts."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, manifest
from native_application_session import NativeApplicationSession
from native_application_adapters import FrozenApplicationAdapters
from native_fixture_transport import verify, MODE

AREA = Path('D:/agent-task-runs/wsc-a3-closeout-20261026-v1')
PRIOR = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')


def smoke(arm):
    reg = read(AREA / ('runtime-' + arm + '.json'))
    session = NativeApplicationSession(reg, AREA / ('native-fixture-' + arm))
    reg['initial_manifest'] = session.source_manifest()
    original = dict(reg['initial_manifest'])
    try:
        session.open()
        target = Path(reg['workspace']) / '.wsc-probes' / ('transport-' + session.opened['thread']['id'])
        script = Path(__file__).parent / 'fixture_native_smoke.mjs'
        result = session.server.call('command/exec', dict(command=[reg['node_executable'], str(script),
            str(Path(reg['workspace']) / 'gui'), reg['fixture_root'], str(target)], cwd=reg['workspace'],
            sandboxPolicy=dict(type='workspaceWrite', writableRoots=[reg['workspace']], networkAccess=False), timeoutMs=30000), timeout=40)
        save(AREA / ('fixture-' + arm + '-execution.json'), result)
        assert result['exitCode'] == 0
        value = read(target / 'result.json')
        assert value['passed'] and session.source_manifest() == original
    finally:
        cleanup = session.close()
    assert cleanup['empty_confirmed']
    return dict(result=value, cleanup=cleanup, source_manifest_unchanged=True)


if __name__ == '__main__':
    assert not (AREA / 'prepared.json').exists()
    reg = read(PRIOR / 'registration.json')
    frozen = read(reg['tasks']['a3']['binding'])['workspace']
    hashes = []
    for arm in ('B', 'C'):
        runtime = read(AREA / ('runtime-' + arm + '.json'))
        verify(runtime['fixture_root'], frozen)
        hashes.append(file_hash(Path(runtime['fixture_root']) / 'harness/browser-host.mjs'))
    assert hashes[0] == hashes[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        observations = dict(zip(('B', 'C'), pool.map(smoke, ('B', 'C'))))
    save(AREA / 'native-fixture-admission.json', observations)
    conditions = {**reg['conditions'], 'fixture_transport': MODE}
    job = deepcopy(next(job for job in reg['jobs'] if job['arm'] == 'C'))
    job['resources']['output'] = str(AREA)
    adapter = FrozenApplicationAdapters(conditions, reg['tasks'], reg['expected_checks'], node_executable=reg['node_executable'])
    grade = adapter.grade(job, 3, AREA / 'isolated-S3-acceptance')
    assert all(row['passed'] for row in grade['observations'])
    save(AREA / 'isolated-S3-grade.json', grade)
    previous = Path('D:/agent-task-runs/wsc-a3-c-continuation-20261026-v1')
    current = manifest(Path(job['resources']['workspace']) / 'gui/src')
    paths = [AREA / 'isolated-S3-acceptance/registration.json',
        previous / 'S3-supplemental/registration.json', previous / 'S3-graph-check/registration.json']
    assert all(read(path)['source_manifest'] == current for path in paths)
    save(AREA / 'prepared.json', dict(native_fixture=observations, fixture_host_sha256=hashes[0], grade=grade,
        current_source_manifest=current, same_source_as_previous_supplemental=True,
        conditions=conditions, model_calls=0, scope='Both native fixture routes and new adapter integration; existing source unchanged'))
    print(dict(status='prepared', model_calls=0, native_arms=2, isolated_grade_passed=11), flush=True)
