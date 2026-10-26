"""Offline replay only; never promotes missing historical process evidence."""
from pathlib import Path
from hashlib import sha256
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_controlled_boundary import assess_wait, seal_controlled_stop

SOURCE = Path('D:/agent-task-runs/native-boundary-capability-20261026-v3')
OUTPUT = Path('D:/agent-task-runs/wsc-controlled-boundary-guards-20261026-v1')
OUTPUT.mkdir(exist_ok=False)
read = lambda name: json.loads((SOURCE / name).read_text(encoding='utf-8'))
callback = read('held-callback.json')
events = [json.loads(line) for line in (SOURCE / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
cut = next(i for i, event in enumerate(events) if event == callback)
held = (SOURCE / 'held-native.jsonl').read_bytes()
closed = (SOURCE / 'closed-native.jsonl').read_bytes()
cleanup = read('result.json')['cleanup']
root = cleanup['root_pids'][0]
actual = assess_wait(held, callback, events[:cut + 1], root_pid=root, owned_members=None)
assert not actual.admitted and 'owned_processes_not_drained_or_unknown' in actual.reasons
# Counterfactual input solely tests structural rejection of the known closed tail.
# It is not an observation of process membership during the old trial.
structural = assess_wait(held, callback, events[:cut + 1], root_pid=root, owned_members=[root])
rejection = None
if structural.admitted:
    try:
        seal_controlled_stop(structural, held, closed, cleanup)
    except ValueError as exc:
        rejection = str(exc)
assert structural.admitted and rejection == 'controlled_stop_extra_execution'
result = dict(scope='offline historical replay and conservative rejection; no native operations',
    real_model_calls=0, historical_trial_promoted=False, actual_gate_reasons=actual.reasons,
    assumed_root_only_structural_gate=structural.admitted,
    root_only_membership_observed=False, closed_archive_rejection=rejection,
    whole_campaign_usage_complete=False,
    input_sha256={name: sha256((SOURCE / name).read_bytes()).hexdigest() for name in
        ('held-callback.json', 'events.jsonl', 'held-native.jsonl', 'closed-native.jsonl', 'result.json')},
    implementation_sha256=sha256((ROOT / 'experiments/native_controlled_boundary.py').read_bytes()).hexdigest())
with (OUTPUT / 'audit.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False))
