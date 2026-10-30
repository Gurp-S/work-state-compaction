"""Known answer and cross-run history locations; never returns answer values."""
from pathlib import Path


def private_inventory(root, readiness):
    root = Path(root).resolve()
    fixtures = {Path(p).parent.resolve() for p in readiness['task_fixture_roots'].values()}
    fixtures.add(Path(readiness['task_fixture_superseded']).resolve())
    failed = Path('D:/agent-task-runs/wsc-matrix-t4-admission-20261028-v1')
    if failed.exists():
        fixtures.add(failed)
    blocked = fixtures | {root/'benchmarks/acceptance_matrix_v1', root/'tests', root/'versions',
                          root/'reviews/acceptance-matrix-admission-20261028'}
    for name in ('sessions', 'archived_sessions', 'memories'):
        path = Path.home()/'.codex'/name
        if path.is_dir():
            blocked.add(path.resolve())
    return sorted(blocked), sorted(fixtures)
