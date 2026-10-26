"""Incremental C policy version, scoped runtime proof and read-only S2 plan."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'versions/20261026-native-auto-compaction-capability-v0.6-delta.zip'
TARGET = ROOT / 'versions/20261026-C-auto-compaction-policy-v0.7-delta.zip'
PROBE = Path('D:/agent-task-runs/native-post-compaction-access-20261026-v1')
POLICY = Path('D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1')
hashfile = lambda p: sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
audit = read(PROBE / 'audit.json')
policy = read(POLICY / 'result.json')
assert audit['post_compaction_tool_access'] and audit['all_local_usage_complete'] and audit['cleanup_empty']
assert all(hashfile(PROBE / name) == value for name, value in audit['inputs_sha256'].items())
assert policy['effective_limit'] == 96000 and policy['model_calls'] == 0 and 'error' not in policy
assert all(hashfile(ROOT / name) == value for name, value in policy['implementation_sha256'].items())
files = {}
for name in ('experiments/native_c_auto_compaction.py', 'experiments/native_host_controls.py',
    'experiments/native_application_worker.py', 'experiments/NATIVE-LOCAL-HANDOFF.md',
    'tests/test_native_c_auto_compaction.py', 'tests/test_native_host_controls.py',
    'reviews/2026-10-26-post-compaction-access-and-C-policy.md',
    'validation/matrix-runtime-20261026/probe_native_post_compaction_access.py',
    'validation/matrix-runtime-20261026/audit_native_post_compaction_access.py',
    'validation/matrix-runtime-20261026/admit_c_auto_compaction_policy.py',
    'validation/matrix-runtime-20261026/plan_c_auto_compaction_s2_restore.py',
    'validation/matrix-runtime-20261026/package_c_auto_compaction.py'):
    files[name] = ROOT / name
for name in ('registration.json', 'controller.py', 'startup-grant.json', 'post-grant.json', 'preflight.json',
    'post-request-binding.json', 'process-observations.json', 'startup-phase.json', 'post-phase.json',
    'result.json', 'audit.json', 'next-admission-envelope.json'):
    files['evidence/post-compaction-access/' + name] = PROBE / name
for name in ('registration.json', 'result.json', 's2-restore-plan.json', 'next-admission-envelope.json'):
    files['evidence/C-policy/' + name] = POLICY / name
index = dict(format='C_auto_compaction_policy_v0.7', base=str(BASE), base_sha256=hashfile(BASE),
    files={name: hashfile(path) for name, path in files.items()},
    known_tokens=156789, known_responses=6, native_tool_access_proven=True,
    scope='One PowerShell session across native compaction; C-only opt-in hook with actual readback; read-only S2 restore plan',
    tests=dict(new_passed=4, existing_host_controls_passed=3, full_regression=False),
    application_qualified=False, WSC_benefit_proven=False, whole_campaign_usage_complete=False,
    excluded=['native histories', 'reasoning contents', 'dependencies', 'databases', 'old S3 artifact contents'])
with zipfile.ZipFile(TARGET, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, path in files.items():
        archive.write(path, name)
    archive.writestr('VERSION.json', json.dumps(index, ensure_ascii=False, indent=2))
with zipfile.ZipFile(TARGET) as archive:
    assert archive.testzip() is None
    assert all(sha256(archive.read(name)).hexdigest() == value for name, value in index['files'].items())
receipt = dict(path=str(TARGET), sha256=hashfile(TARGET), bytes=TARGET.stat().st_size, files=len(files))
with (POLICY / 'delivery.json').open('x', encoding='utf-8') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2)
print(json.dumps(receipt, ensure_ascii=False))
