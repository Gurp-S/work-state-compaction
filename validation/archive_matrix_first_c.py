"""Preserve scoped first-C evidence without duplicating runtime binaries."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'versions/matrix-first-C-findings-v1.50-delta.zip'
REVIEW = ROOT / 'reviews/acceptance-matrix-admission-20261028'


def main():
    readiness = json.loads((REVIEW / 'readiness.json').read_text(encoding='utf-8'))
    readiness.update(status='first_C_artifact_passed_run_budget_interrupted',
        first_batch_known_tokens=1375135, first_batch_known_responses=37,
        first_batch_known_values_are_lower_bounds=True,
        dispatch_budget_wired_to_native_matrix=True,
        dispatch_budget_unit_checks_passed=11,
        scope='T1 strong-model C artifact only; no valid B/C comparison. Unknown usage retained; arithmetic remainder frozen.')
    (REVIEW / 'readiness.json').write_text(json.dumps(readiness, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    files = {}
    patterns = ['src/**/*.py', 'experiments/native_*.py',
        'experiments/NATIVE-LOCAL-HANDOFF.md', 'benchmarks/acceptance_matrix_v1/**/*.py',
        'validation/*.py', 'tests/test_native*.py', 'tests/test_matrix*.py',
        'reviews/acceptance-matrix*', 'reviews/acceptance-matrix-admission-20261028/**/*']
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if path.is_file() and '__pycache__' not in path.parts:
                files['wsc/'+path.relative_to(ROOT).as_posix()] = path
    names = ['wsc-matrix-first-pair-20261028-v1',
        'wsc-matrix-first-pair-20261028-r2-v2',
        'wsc-matrix-selector-boundary-20261028-v1']
    names += ['wsc-matrix-python-admission-20261028-v'+str(n) for n in range(1,5)]
    for name in names:
        folder = Path('D:/agent-task-runs')/name
        for path in folder.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts: continue
            if '.runtime' in path.parts and path.name != 'runtime-manifest.json': continue
            if path.suffix.lower() in {'.exe','.dll','.zip','.pyc'}: continue
            files['evidence/'+name+'/'+path.relative_to(folder).as_posix()] = path
    entries = {name:dict(bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest())
        for name,path in sorted(files.items())}
    with ZipFile(TARGET, 'x', compression=ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()): archive.write(path,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,ensure_ascii=False,indent=2))
    with ZipFile(TARGET) as archive:
        if archive.testzip() is not None: raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(TARGET),bytes=TARGET.stat().st_size,
        sha256=sha256(TARGET.read_bytes()).hexdigest(),files=len(entries),
        scope='Scoped delta and raw evidence; runtime binaries retained at original paths, not duplicated.')
    TARGET.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
