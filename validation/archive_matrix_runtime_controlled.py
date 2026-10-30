"""Archive failed admission, source versions and zero-inference fixes compactly."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'versions/matrix-runtime-controlled-v1.52-delta.zip'
RUN=Path('D:/agent-task-runs/wsc-matrix-runtime-controlled-20261028-v1')


def main():
    readiness=ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json'
    value=json.loads(readiness.read_text(encoding='utf-8'))
    value.update(runtime_controlled_group=str(RUN),runtime_controlled_A_checks_passed=11,
        runtime_controlled_A_tokens=262500,runtime_controlled_A_responses=6,
        runtime_controlled_A_phase_usage_complete=True,runtime_controlled_group_valid=False,
        runtime_controlled_no_history_failure='F5_empty_native_injection',
        runtime_controlled_no_history_model_dispatched=False,
        runtime_group_reconciliation=str(RUN/'per-run-reconciliation.json'),
        total_known_tokens_lower_bound=1637635,total_known_response_receipts=43,
        whole_campaign_usage_complete=False,paid_dispatch_admitted=False,
        actual_current_cli='C:/Users/48522/AppData/Local/OpenAI/Codex/bin/08d187884f2330d1/codex.exe',
        material_transport_admission='D:/agent-task-runs/wsc-matrix-material-admission-20261029-v2',
        empty_material_checks_passed=3,structured_final_checks_passed=6,
        status='runtime_group_failed_before_C_B_material_transport_fixed_zero_inference')
    readiness.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files={}
    for pattern in ('benchmarks/acceptance_matrix_v1/*.py','validation/*matrix*.py',
                    'tests/test_matrix*.py','reviews/2026-10-28-acceptance-matrix-execution-v1.5.md',
                    'reviews/acceptance-matrix-runtime-controlled-findings.md',
                    'reviews/acceptance-matrix-admission-20261028/readiness.json',
                    'experiments/NATIVE-LOCAL-HANDOFF.md'):
        for p in ROOT.glob(pattern):
            if p.is_file():files['wsc/'+p.relative_to(ROOT).as_posix()]=p
    roots=[RUN]+[Path('D:/agent-task-runs/wsc-matrix-material-admission-20261029-v'+str(i)) for i in (1,2)]
    for folder in roots:
        for p in folder.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts:continue
            if '.runtime' in p.parts and p.name!='runtime-manifest.json':continue
            if p.suffix.lower() in ('.exe','.dll','.zip','.pyc'):continue
            files['evidence/'+folder.name+'/'+p.relative_to(folder).as_posix()]=p
    claim=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1/matrix-second-batch-20261028.claim.json')
    files['evidence/parent-second-allocation-claim.json']=claim
    entries={name:dict(bytes=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest()) for name,p in sorted(files.items())}
    with ZipFile(TARGET,'x',compression=ZIP_DEFLATED) as archive:
        for name,p in sorted(files.items()):archive.write(p,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,indent=2))
    with ZipFile(TARGET) as archive:
        if archive.testzip() is not None:raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(TARGET),bytes=TARGET.stat().st_size,sha256=sha256(TARGET.read_bytes()).hexdigest(),
        files=len(entries),base='matrix-shared-runtime-v1.51-delta.zip',runtime_binaries_duplicated=False)
    TARGET.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
