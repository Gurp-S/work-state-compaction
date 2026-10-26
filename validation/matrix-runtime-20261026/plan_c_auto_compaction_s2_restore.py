"""Read-only plan: retain S3 delta before reusing private dependencies at S2."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_application_session import NativeApplicationSession
OLD = Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
AREA = Path('D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1')
FROZEN = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/staged/frozen-workspace')
prepared = read(OLD / 'prepared.json')
reg = prepared['registration']
work = Path(reg['workspace']).resolve()
measurer = NativeApplicationSession(reg, AREA / 'manifest-only')
current = measurer.source_manifest()
expected = reg['initial_manifest']
changed = [name for name in expected if name in current and current[name] != expected[name]]
missing = sorted(set(expected) - set(current))
extra = sorted(set(current) - set(expected))
entries = []
for name in changed:
    source = FROZEN / name
    entries.append(dict(path=name, current_sha256=current[name], expected_sha256=expected[name],
        restore_source=str(source), restore_source_matches=source.is_file() and file_hash(source) == expected[name]))
plan = dict(scope='Read-only plan only; no workspace/source/dependency changes', workspace=str(work),
    changed=entries, missing=missing, extra=extra,
    changed_files_restorable=not missing and all(e['restore_source_matches'] for e in entries),
    old_result_sha256=file_hash(OLD / 'result.json'), old_prepared_sha256=file_hash(OLD / 'prepared.json'),
    required_before_mutation=['archive current changed/extra files with manifest', 'verify old S3 code against its archived receipt',
        'restore only expected hash-bound source and then verify exact initial_manifest',
        'retain private node_modules/browser directories without copying',
        'new registration/cumulative envelope and grader pins; never rerun old driver'],
    model_calls=0, paid_execution_permitted=False)
save(AREA / 's2-restore-plan.json', plan)
print(dict(changed=len(changed), missing=len(missing), extra=len(extra),
    changed_files_restorable=plan['changed_files_restorable'], model_calls=0))
