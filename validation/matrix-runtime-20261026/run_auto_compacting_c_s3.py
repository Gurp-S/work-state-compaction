"""One new S2->S3 qualification, reusing the existing driver and all caps."""
from pathlib import Path
import math
import sys
import time
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_campaign_envelope import qualification_envelope
from run_calibrated_dev import execute

OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
POLICY = Path('D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1')
PROTOCOL = Path('D:/agent-task-runs/native-post-compaction-access-20261026-v1')
assert read(OUT / 'S2-restoration.json')['exact_initial_manifest']
assert read(POLICY / 'result.json')['model_calls'] == 0 and read(POLICY / 'result.json')['cleanup']['empty_confirmed']
previous = read(PROTOCOL / 'result.json')
assert previous['cleanup']['empty_confirmed'] and not previous['ledger']['inflight'] and not previous['ledger']['study']['uncertain']
parent = OUT / 'closed-parent-projection'
parent.mkdir(exist_ok=False)
# The last closed inference ledger plus the later zero-inference envelope are
# explicitly projected for the reused driver's input schema, never fabricated
# as a new receipt or a whole-campaign complete ledger.
save(parent / 'registration.json', read(PROTOCOL / 'registration.json'))
save(parent / 'result.json', {**previous, 'whole_campaign_usage_complete': False,
    'projection_source': dict(path=str(PROTOCOL / 'result.json'), sha256=file_hash(PROTOCOL / 'result.json')),
    'later_zero_model_configuration_check': dict(path=str(POLICY / 'result.json'), sha256=file_hash(POLICY / 'result.json'))})
envelope = read(POLICY / 'next-admission-envelope.json')
envelope['remaining_limits']['max_seconds'] -= math.ceil(max(0, time.time() - (POLICY / 'next-admission-envelope.json').stat().st_mtime))
save(parent / 'next-admission-envelope.json', envelope)
save(OUT / 'experiment-intervention.json', dict(scope='One C qualification; not formal B/C',
    native_internal_auto_compaction=96000, same_original_S2=True, same_original_S3=True,
    WSC_selection_regenerated=False, extra_model_directives=False, native_B_changed=False,
    arm_limit_tokens=6000000, arm_limit_responses=120, arm_limit_seconds=2700, automatic_retries=0,
    controls_source=str(ROOT / 'experiments/native_c_auto_compaction.py'),
    controls_sha256=file_hash(ROOT / 'experiments/native_c_auto_compaction.py'),
    wrapper_sha256=file_hash(Path(__file__)), reused_driver_sha256=file_hash(Path(__file__).with_name('run_calibrated_dev.py'))))
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
execute(OUT=OUT, ordinary_time_shared=True, budget_parent=parent)
result = read(OUT / 'result.json')
registration = read(OUT / 'registration.json')
elapsed = max(0, time.time() - (OUT / 'registration.json').stat().st_mtime)
next_envelope = qualification_envelope(result['ledger'], [], elapsed)
next_envelope.update(old_unknowns_preserved=True, whole_campaign_usage_complete=False,
    parent_result=dict(path=str(OUT / 'result.json'), sha256=file_hash(OUT / 'result.json')))
save(OUT / 'next-admission-envelope.json', next_envelope)
