"""Freeze cohort registration/seed and preserved zero-model setup failures."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT=Path(__file__).resolve().parents[2]
AREA=Path('D:/agent-task-runs/wsc-a3-fixed-S2-repeated-BC-20261026-v1')
BASE=ROOT/'versions/20261026-auto-compacting-C-S3-qualified-v0.8-delta.zip'
TARGET=ROOT/'versions/20261026-fixed-S2-repeated-BC-registered-v0.9-delta.zip'
hashfile=lambda p:sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
seed=read(AREA/'B-seed-v2/result.json')
assert seed['completed'] and seed['usage_complete'] and seed['cleanup']['empty_confirmed']
assert read(AREA/'R01/pair-result.json')['ledger']['study']['tokens']==0
files={}
for name in ('experiments/native_s2_workspace_restore.py','experiments/native_package_media.py','experiments/NATIVE-LOCAL-HANDOFF.md',
    'validation/matrix-runtime-20261026/prepare_fixed_S2_repeated_BC.py',
    'validation/matrix-runtime-20261026/generate_fixed_native_B_seed.py',
    'validation/matrix-runtime-20261026/run_fixed_S2_repeated_BC.py',
    'validation/matrix-runtime-20261026/grade_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/package_fixed_S2_repeated_setup.py'):
    files[name]=ROOT/name
for name in ('registration.json','shared-raw-observations.json','C-package.json','execution-contract.json',
    'cohort-controller.py','cohort-result.json','R01/registration.json','R01/pair-result.json','R01/next-admission-envelope.json',
    'execution-v2/execution-contract.json','execution-v2/cohort-controller.py'):
    files['evidence/repeated-BC/'+name]=AREA/name
for folder in ('B-seed','B-seed-v2'):
    for name in ('registration.json','result.json','phase-journal.json','settlement.json','next-admission-envelope.json','controller.py'):
        path=AREA/folder/name
        if path.is_file():files['evidence/repeated-BC/'+folder+'/'+name]=path
for arm in ('B','C'):
    for name in ('result.json','move-plan.json'):
        files['evidence/repeated-BC/preserved-before-'+arm+'/'+name]=AREA/('preserved-before-'+arm)/name
    files['evidence/repeated-BC/zero-model-attempt/'+arm+'/result.json']=AREA/'R01'/arm/'result.json'
index=dict(format='fixed_S2_repeated_BC_registered_v0.9',base=str(BASE),base_sha256=hashfile(BASE),
    files={name:hashfile(path) for name,path in files.items()},registered_pairs=3,actor_variability_only=True,
    native_B_seed_tokens=197577,native_B_seed_usage_complete=True,
    initial_actor_setup_attempt_tokens=0,fixed_WSC_package_reused=True,
    state='Execution-v2 started; not a result snapshot',whole_campaign_usage_complete=False,
    full_five_task_matrix_completed=False,WSC_semantic_attribution_proven=False,
    excluded=['live histories','reasoning contents','runtime dependencies','database copies','live source changes'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(path=str(TARGET),sha256=hashfile(TARGET),bytes=TARGET.stat().st_size,files=len(files))
with (AREA/'registered-delivery.json').open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
print(json.dumps(receipt,ensure_ascii=False))
