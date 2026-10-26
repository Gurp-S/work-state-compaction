"""Small delta of a real C qualification, not a formal native comparison."""
from pathlib import Path
from hashlib import sha256
import json
import math
import time
import zipfile
ROOT = Path(__file__).resolve().parents[2]
AREA = Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
BASE = ROOT/'versions/20261026-C-auto-compaction-policy-v0.7-delta.zip'
TARGET = ROOT/'versions/20261026-auto-compacting-C-S3-qualified-v0.8-delta.zip'
hashfile = lambda p: sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
audit = read(AREA/'closed-review.json')
assert audit['qualification_passed'] and audit['independent_checks_passed']==17
assert all(hashfile(AREA/name)==value for name,value in audit['inputs_sha256'].items())
envelope = read(AREA/'next-admission-envelope.json')
elapsed = max(0,time.time()-(AREA/'next-admission-envelope.json').stat().st_mtime)
envelope['remaining_limits']['max_seconds'] -= math.ceil(elapsed)
envelope['parent_envelope_sha256'] = hashfile(AREA/'next-admission-envelope.json')
envelope['post_run_review_elapsed_seconds'] = elapsed
envelope['old_unknowns_preserved'] = True
envelope['whole_campaign_usage_complete'] = False
with (AREA/'post-review-admission-envelope.json').open('x',encoding='utf-8') as stream:
    json.dump(envelope,stream,ensure_ascii=False,indent=2)
files = {}
for name in ('experiments/NATIVE-LOCAL-HANDOFF.md','reviews/2026-10-26-auto-compacting-C-S3-result.md',
    'validation/matrix-runtime-20261026/prepare_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/run_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/grade_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/audit_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/package_auto_compacting_c_s3.py',
    'validation/matrix-runtime-20261026/s3-concurrency-direct.mjs',
    'validation/matrix-runtime-20261026/s3-scope-check.mjs',
    'validation/matrix-runtime-20261026/check_s2_clipping.mjs'):
    files[name]=ROOT/name
for p in AREA.glob('*.json'):
    files['evidence/auto-C-S3/'+p.name]=p
files['evidence/auto-C-S3/controller.py']=AREA/'controller.py'
files['evidence/auto-C-S3/retained-S3-six-source-files.zip']=AREA/'retained-S3-six-source-files.zip'
for folder in ('S3-acceptance','S3-concurrency','S3-scope','S3-clipping','browser-capability','cold-access'):
    for p in (AREA/folder).glob('*.json'):
        files['evidence/auto-C-S3/'+p.relative_to(AREA).as_posix()]=p
for name in ('S3-clipping/after-wheel.png','S3-scope/selected.png'):
    files['evidence/auto-C-S3/'+name]=AREA/name
reg=read(AREA/'prepared.json')['registration']
work=Path(reg['workspace'])
for name,value in audit['changed_source_files'].items():
    assert hashfile(work/name)==value
    files['isolated-C-source/'+name]=work/name
index=dict(format='auto_compacting_C_S3_qualified_v0.8',base=str(BASE),base_sha256=hashfile(BASE),
    files={name:hashfile(path) for name,path in files.items()},known_tokens=4197357,responses=62,
    usage_complete=True,compactions=2,scoped_S3_qualification_passed=True,independent_checks_passed=17,
    semantic_advantage_over_native_proven=False,formal_BC_started=False,whole_campaign_usage_complete=False,
    excluded=['native histories','reasoning contents','databases','dependencies','retained S3 validation contents','full image set'])
with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,path in files.items():archive.write(path,name)
    archive.writestr('VERSION.json',json.dumps(index,ensure_ascii=False,indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest()==value for name,value in index['files'].items())
receipt=dict(path=str(TARGET),sha256=hashfile(TARGET),bytes=TARGET.stat().st_size,files=len(files),
    next_admission=str(AREA/'post-review-admission-envelope.json'),remaining_limits=envelope['remaining_limits'])
with (AREA/'delivery.json').open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
print(json.dumps(receipt,ensure_ascii=False))
