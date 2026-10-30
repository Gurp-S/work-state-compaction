"""First valid paired result; small delta without Python/Codex binaries."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
RUN=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')
TARGET=ROOT/'versions/matrix-first-valid-pair-v1.53-delta.zip'


def main():
    readiness=ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json'
    value=json.loads(readiness.read_text(encoding='utf-8'))
    value.update(status='first_current_version_valid_pair_complete',valid_BC_comparisons=1,
        formal_native_B_compressions_executed=1,current_valid_pair=str(RUN),
        fixed_version_valid_repetitions=1,required_repetitions=3,
        current_group_usage_complete=True,whole_campaign_usage_complete=False,
        total_known_tokens_lower_bound=2712657,total_known_response_receipts=74,
        paid_dispatch_admitted=False,old_failures_and_unknowns_preserved=True,
        observed_C_total_tokens=224906,observed_Bprime_total_tokens=256199,
        observed_C_uncached_input_tokens=61926,observed_Bprime_uncached_input_tokens=23928,
        monetary_savings_proven=False,stable_superiority_proven=False)
    readiness.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files={}
    for pattern in ('benchmarks/acceptance_matrix_v1/*.py','tests/test_matrix*.py','validation/*matrix*.py',
                    'reviews/2026-10-29-acceptance-matrix-execution-v1.6.md',
                    'reviews/acceptance-matrix-first-valid-pair-report.md',
                    'reviews/acceptance-matrix-admission-20261028/readiness.json',
                    'experiments/NATIVE-LOCAL-HANDOFF.md'):
        for path in ROOT.glob(pattern):
            if path.is_file():files['wsc/'+path.relative_to(ROOT).as_posix()]=path
    for path in RUN.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:continue
        if '.runtime' in path.parts and path.name!='runtime-manifest.json':continue
        if path.suffix.lower() in ('.exe','.dll','.zip','.pyc'):continue
        files['evidence/'+RUN.name+'/'+path.relative_to(RUN).as_posix()]=path
    claim=Path('D:/agent-task-runs/wsc-matrix-runtime-controlled-20261028-v1/next-runtime-group.claim.json')
    files['evidence/closed-parent-residual-claim.json']=claim
    entries={name:dict(bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest()) for name,path in sorted(files.items())}
    with ZipFile(TARGET,'x',compression=ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):archive.write(path,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,indent=2))
    with ZipFile(TARGET) as archive:
        if archive.testzip() is not None:raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(TARGET),bytes=TARGET.stat().st_size,sha256=sha256(TARGET.read_bytes()).hexdigest(),
        files=len(entries),base='matrix-runtime-controlled-v1.52-delta.zip',runtime_binaries_duplicated=False)
    TARGET.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
