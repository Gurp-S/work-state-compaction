"""Small version delta; runtime binaries remain at their existing local paths."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'versions/matrix-shared-runtime-v1.51-delta.zip'
EVIDENCE=Path('D:/agent-task-runs/wsc-matrix-shared-runtime-20261028-v1')


def main():
    ready=ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json'
    value=json.loads(ready.read_text(encoding='utf-8'))
    value.update(shared_workspace_runtime_wired=True,shared_runtime_native_admission=str(EVIDENCE),
        shared_runtime_native_arms_qualified=['Bprime','C'],shared_runtime_unit_checks_passed=5,
        current_runtime_model_calls=0,paid_dispatch_admitted=False,
        prior_history_control_scope='T1 strong model, previous execution environment only')
    ready.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    names=['benchmarks/acceptance_matrix_v1/workspace_runtime.py',
        'validation/run_matrix_pair.py','validation/qualify_matrix_pair_runtime.py',
        'validation/archive_matrix_shared_runtime.py','tests/test_matrix_workspace_runtime.py',
        'reviews/acceptance-matrix-shared-runtime-report.md',
        'reviews/acceptance-matrix-admission-20261028/readiness.json',
        'experiments/NATIVE-LOCAL-HANDOFF.md']
    files={'wsc/'+name:ROOT/name for name in names}
    for p in EVIDENCE.rglob('*'):
        if not p.is_file():continue
        if '.runtime' in p.parts and p.name!='runtime-manifest.json':continue
        files['evidence/'+EVIDENCE.name+'/'+p.relative_to(EVIDENCE).as_posix()]=p
    entries={name:dict(bytes=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest()) for name,p in sorted(files.items())}
    with ZipFile(OUT,'x',compression=ZIP_DEFLATED) as archive:
        for name,p in sorted(files.items()):archive.write(p,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,indent=2))
    with ZipFile(OUT) as archive:
        if archive.testzip() is not None:raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(OUT),bytes=OUT.stat().st_size,sha256=sha256(OUT.read_bytes()).hexdigest(),
        files=len(entries),base='matrix-first-C-findings-v1.50-delta.zip',runtime_binary_duplication=False)
    OUT.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
