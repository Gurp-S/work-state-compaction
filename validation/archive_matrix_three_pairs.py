"""Preserve repeated results, all samples and input audit without binary copies."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
RUN=Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1')
TARGET=ROOT/'versions/matrix-three-pairs-v1.54-delta.zip'


def main():
    ready=ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json'
    value=json.loads(ready.read_text(encoding='utf-8'))
    value.update(status='T1_current_strategy_three_pairs_complete',valid_BC_comparisons=3,
        formal_native_B_compressions_executed=3,fixed_version_valid_repetitions=3,
        current_repetition_group=str(RUN),current_repetition_group_usage_complete=True,
        current_strategy_C_successes=3,current_strategy_Bprime_successes=3,
        current_strategy_C_total_tokens=719653,current_strategy_Bprime_total_tokens=794192,
        current_strategy_C_uncached_tokens=175482,current_strategy_Bprime_uncached_tokens=94162,
        total_known_tokens_lower_bound=3745397,total_known_response_receipts=105,
        whole_campaign_usage_complete=False,old_failures_and_unknowns_preserved=True,
        stable_superiority_proven=False,monetary_savings_proven=False,paid_dispatch_admitted=False,
        next_step='Engine-only identity metadata sidecar design and exact-restoration checks; no semantic selection change or broad paid expansion.')
    ready.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files={}
    for pattern in ('benchmarks/acceptance_matrix_v1/*.py','tests/test_matrix*.py','validation/*matrix*.py',
                    'reviews/2026-10-29-acceptance-matrix-execution-v1.7.md',
                    'reviews/acceptance-matrix-three-pair-report.md',
                    'reviews/acceptance-matrix-admission-20261028/readiness.json',
                    'experiments/NATIVE-LOCAL-HANDOFF.md'):
        for path in ROOT.glob(pattern):
            if path.is_file():files['wsc/'+path.relative_to(ROOT).as_posix()]=path
    for path in RUN.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:continue
        if '.runtime' in path.parts and path.name!='runtime-manifest.json':continue
        if path.suffix.lower() in ('.exe','.dll','.zip','.pyc'):continue
        files['evidence/'+RUN.name+'/'+path.relative_to(RUN).as_posix()]=path
    claim=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1/matrix-third-batch-20261029.claim.json')
    files['evidence/third-allocation-claim.json']=claim
    entries={name:dict(bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest()) for name,path in sorted(files.items())}
    with ZipFile(TARGET,'x',compression=ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):archive.write(path,name)
        archive.writestr('archive-manifest.json',json.dumps(entries,indent=2))
    with ZipFile(TARGET) as archive:
        if archive.testzip() is not None:raise ValueError('archive_integrity_failure')
    receipt=dict(path=str(TARGET),bytes=TARGET.stat().st_size,sha256=sha256(TARGET.read_bytes()).hexdigest(),
        files=len(entries),base='matrix-first-valid-pair-v1.53-delta.zip',runtime_binaries_duplicated=False)
    TARGET.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
