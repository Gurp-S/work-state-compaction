"""Small immutable delta: R02 receipts, observer fix, and independent audit."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile

ROOT=Path(__file__).resolve().parents[2]
COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
BASE=ROOT/'versions/20261027-repeat-admission-and-scope-review-v1.0-delta.zip'
TARGET=ROOT/'versions/20261027-R02-terminal-review-v1.1-delta.zip'
hashfile=lambda p:sha256(p.read_bytes()).hexdigest()
files={name:ROOT/name for name in (
    'experiments/native_cleanup_terminal.py','experiments/native_application_session.py',
    'experiments/NATIVE-LOCAL-HANDOFF.md','tests/test_native_cleanup_terminal.py',
    'reviews/2026-10-27-second-fixed-S2-BC-pair.md',
    'validation/matrix-runtime-20261026/review_R02_terminal_without_models.py',
    'validation/matrix-runtime-20261026/package_R02_terminal_review.py')}
for name in ('execution-v3/cohort-result.json','execution-v3/R02/pair-result.json',
             'execution-v3/R02/registration.json','execution-v3/R02/next-admission-envelope.json',
             'execution-v3/R02/next-repetition-admission.json'):
    files['evidence/'+name]=COHORT/name
for arm in ('B','C'):
    for name in ('result.json','qualification.json','S3-grade.json','supplemental-grade.json',
                 'scope-diagnostic-grade.json','S3-phase/phase-outcome.json','receiver/process-cleanup.json'):
        relative='execution-v3/R02/'+arm+'/'+name
        files['evidence/'+relative]=COHORT/relative
files['evidence/terminal-audit.json']=Path('D:/agent-task-runs/wsc-R02-terminal-review-20261027-v1/audit.json')
index=dict(format='R02_terminal_review_v1.1',base=str(BASE),base_sha256=hashfile(BASE),
    files={name:hashfile(path) for name,path in files.items()},offline_tests_passed=9,
    model_calls_during_terminal_review=0,original_results_unchanged=True,
    B_full_usage_complete=False,C_completed=True,both_exceeded_cap=True,R03_started=False,
    full_goal_achieved=False,WSC_relative_economic_benefit_proven=False,
    excluded=['raw native histories','reasoning','dependencies','workspace source copies'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(path=str(TARGET),sha256=hashfile(TARGET),bytes=TARGET.stat().st_size,files=len(files))
with (COHORT/'R02-terminal-review-delivery.json').open('x',encoding='utf-8') as stream:
    json.dump(receipt,stream,ensure_ascii=False,indent=2)
print(json.dumps(receipt,ensure_ascii=False))
