"""Small sidecar delta, including negative/positive qualification history."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'versions/hot-projection-sidecar-v1.55-delta.zip'


def main():
    ready=ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json'
    value=json.loads(ready.read_text(encoding='utf-8'))
    value.update(status='hot_identity_sidecar_qualified_zero_inference_not_promoted',
        candidate_actor_projection_policy='engine_identity_sidecar_v1',candidate_default_enabled=False,
        candidate_model_task_quality_verified=False,candidate_actual_input_token_savings_verified=False,
        candidate_exact_replay_samples=3,candidate_aliases_verified=72,candidate_unit_checks_passed=7,
        candidate_native_import_confirmed=True,candidate_new_model_calls=0,
        candidate_admission='D:/agent-task-runs/wsc-hot-projection-qualification-20261029-v3',
        paid_dispatch_admitted=False,next_step='Register bounded same-draft old/new continuation diagnostic within existing budget; source/scope mismatch must reject reuse.')
    ready.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    names=['experiments/native_hot_checkpoint.py','experiments/native_indexed_checkpoint.py',
        'experiments/native_snapshot_aliases.py','benchmarks/acceptance_matrix_v1/paired_cell.py',
        'tests/test_native_hot_checkpoint.py','tests/test_matrix_checkpoint_host.py',
        'validation/qualify_hot_projection.py','validation/archive_hot_projection.py',
        'reviews/hot-projection-sidecar-qualification.md',
        'reviews/acceptance-matrix-admission-20261028/readiness.json','experiments/NATIVE-LOCAL-HANDOFF.md']
    files={'wsc/'+name:ROOT/name for name in names}
    for number in (1,2,3):
        folder=Path('D:/agent-task-runs/wsc-hot-projection-qualification-20261029-v'+str(number))
        for path in folder.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:continue
            if path.suffix.lower() in ('.exe','.dll','.zip','.pyc'):continue
            files['evidence/'+folder.name+'/'+path.relative_to(folder).as_posix()]=path
    entries={name:dict(bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest()) for name,path in sorted(files.items())}
    with ZipFile(TARGET,'x',compression=ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):archive.write(path,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,indent=2))
    with ZipFile(TARGET) as archive:
        if archive.testzip() is not None:raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(TARGET),bytes=TARGET.stat().st_size,sha256=sha256(TARGET.read_bytes()).hexdigest(),
        files=len(entries),base='matrix-three-pairs-v1.54-delta.zip',runtime_binaries_duplicated=False)
    TARGET.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
