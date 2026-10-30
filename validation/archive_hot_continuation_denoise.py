"""Retain completed diagnostic and no-model denoise audit without runtime binaries."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'versions/hot-continuation-denoise-audit-v1.57-delta.zip'


def main():
    names = [
        'experiments/native_recorded_choice.py', 'experiments/runtime_denoise_view.mjs',
        'benchmarks/acceptance_matrix_v1/paired_cell.py',
        'tests/test_native_recorded_choice.py', 'tests/test_matrix_cell_identity.py',
        'validation/run_hot_continuation_probe.py', 'validation/summarize_hot_continuation_probe.py',
        'validation/audit_runtime_denoise.mjs', 'validation/audit_runtime_denoise.test.mjs',
        'validation/runtime_denoise_view.test.mjs', 'validation/archive_hot_continuation_denoise.py',
        'reviews/2026-10-29-hot-continuation-probe-v1.md',
        'reviews/hot-projection-continuation-report.md',
        'reviews/runtime-denoise-real-output-audit.md',
        'reviews/runtime-denoise-additional-arm-plan.md',
        'reviews/acceptance-matrix-admission-20261028/runtime-denoise-additional-arm-state.json',
        'experiments/NATIVE-LOCAL-HANDOFF.md',
    ]
    files = {'wsc/' + name: ROOT / name for name in names}
    files['dsh-wsc/lib/denoise.js'] = ROOT.parent / 'dsh-wsc/lib/denoise.js'
    folders = [Path(f'D:/agent-task-runs/wsc-hot-continuation-probe-20261029-v{n}') for n in (1, 2, 3)]
    folders.append(Path('D:/agent-task-runs/wsc-runtime-denoise-admission-20261029-v1'))
    for folder in folders:
        for path in folder.rglob('*'):
            if not path.is_file() or any(part in ('.runtime', '__pycache__', '.git', '.pytest_cache') for part in path.parts):
                continue
            if path.suffix.lower() in ('.exe', '.dll', '.zip', '.pyc'):
                continue
            files['evidence/' + folder.name + '/' + path.relative_to(folder).as_posix()] = path
    entries = {name: dict(bytes=p.stat().st_size, sha256=sha256(p.read_bytes()).hexdigest()) for name, p in sorted(files.items())}
    with ZipFile(TARGET, 'x', compression=ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr('archive-manifest.json', json.dumps(entries, indent=2))
    with ZipFile(TARGET) as archive:
        assert archive.testzip() is None
        for name, entry in entries.items():
            assert sha256(archive.read(name)).hexdigest() == entry['sha256']
    receipt = dict(path=str(TARGET), bytes=TARGET.stat().st_size,
                   sha256=sha256(TARGET.read_bytes()).hexdigest(), files=len(entries),
                   base='runtime-denoise-added-plan-v1.56-delta.zip',
                   runtime_binaries_duplicated=False, new_denoise_model_calls=0)
    TARGET.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
