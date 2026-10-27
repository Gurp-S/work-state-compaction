"""Compact repair/calibration version; live repetitions are not results yet."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT=Path(__file__).resolve().parents[2]
COHORT=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
BASE=ROOT/'versions/20261026-fixed-S2-repeated-BC-registered-v0.9-delta.zip'
TARGET=ROOT/'versions/20261027-repeat-admission-and-scope-review-v1.0-delta.zip'
hashfile=lambda p:sha256(p.read_bytes()).hexdigest()
files={}
for name in ('experiments/native_repeat_admission.py','experiments/native_execution_time.py','experiments/NATIVE-LOCAL-HANDOFF.md',
    'tests/test_native_repeat_admission.py','tests/test_native_execution_time.py',
    'reviews/2026-10-27-first-fixed-S2-BC-pair.md','reviews/2026-10-27-repeat-admission-and-locator-review.md',
    'validation/matrix-runtime-20261026/run_fixed_S2_repeated_BC.py',
    'validation/matrix-runtime-20261026/grade_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/review_repeat_admission_and_quota.py',
    'validation/matrix-runtime-20261026/review_scope_locator_without_models.py',
    'validation/matrix-runtime-20261026/seal_remaining_repetitions.py',
    'validation/matrix-runtime-20261026/report_first_repeated_BC_pair.py',
    'validation/matrix-runtime-20261026/package_repeat_admission_review.py'):
    files[name]=ROOT/name
for name in ('execution-time-policy-adoption.json','execution-v2/cohort-result.json',
    'execution-v3/execution-contract.json','execution-v3/cohort-controller.py',
    'execution-v2/R01/first-report.json','execution-v2/R01/pair-result.json'):
    files['evidence/repeat-repair/'+name]=COHORT/name
for area in ('wsc-repeat-admission-review-20261027-v1','wsc-scope-locator-review-20261027-v1',
             'wsc-remaining-repetitions-admission-20261027-v1'):
    folder=Path('D:/agent-task-runs')/area
    for path in folder.glob('*.json'):files['evidence/repeat-repair/'+area+'/'+path.name]=path
    for path in folder.glob('*.mjs'):files['evidence/repeat-repair/'+area+'/'+path.name]=path
    for path in folder.glob('*/comparison.json'):files['evidence/repeat-repair/'+area+'/'+path.relative_to(folder).as_posix()]=path
index=dict(format='repeat_admission_scope_review_v1.0',base=str(BASE),base_sha256=hashfile(BASE),
    files={name:hashfile(path) for name,path in files.items()},new_offline_tests_passed=6,
    prevented_request_replay=4,token_or_fee_savings_proven=False,primary_grading_unchanged=True,
    actual_execution_time_user_approved=True,old_unknowns_preserved=True,
    state='Remaining repetitions 2 and 3 started; not final cohort result',
    full_goal_achieved=False,WSC_relative_benefit_proven=False,
    excluded=['native histories','reasoning contents','dependencies','GUI reconstruction source copies','live source changes'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(path=str(TARGET),sha256=hashfile(TARGET),bytes=TARGET.stat().st_size,files=len(files))
with (COHORT/'repeat-repair-delivery.json').open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
print(json.dumps(receipt,ensure_ascii=False))
