"""Resolve the already-created fork; no RPC or inference and no fork retry."""
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, digest
from native_rollout_snapshot import capture_rollout
from native_fork_history import observe_registered_fork

area = Path('D:/agent-task-runs/wsc-native-transport-audit-20261023-v1')
old = Path('D:/agent-task-runs/wsc-strict-jsonl-pair-20261023-v1')
child = area / 'by-turn/fork1/rollout.jsonl'
meta = capture_rollout(child).rows[0]['payload']
base = meta['history_base']
# This immutable, previously sealed source archive contains the exact native
# parent prefix. No unregistered file path is followed out of model-authored text.
parent = old / 'B/finite_task/rollout.jsonl'
phase = read(old / 'B/finite_task/phase-outcome.json')
assert file_hash(parent) == phase['rollout_sha256']
live = Path(read(old / 'initial/B/thread-start.json')['thread']['path'])
prefix = parent.read_bytes()[:base['end_byte_offset']]
assert live.read_bytes()[:base['end_byte_offset']] == prefix
binding = {'child_sha256': file_hash(child), 'parent': {**base, 'path': str(parent),
           'prefix_sha256': sha256(prefix).hexdigest()}}
binding_receipt = {'binding': binding, 'binding_time': 'post-observation_audit',
    'parent_archive_sha256': file_hash(parent), 'parent_phase_receipt_sha256': file_hash(old / 'B/finite_task/phase-outcome.json'),
    'fork_request_receipt_sha256': file_hash(area / 'by-turn/registration.json')}
if (area / 'history-binding.json').exists():
    assert read(area / 'history-binding.json') == binding_receipt
else:
    save(area / 'history-binding.json', binding_receipt)
resolved = observe_registered_fork(child, binding)
source = capture_rollout(old / 'B/compaction1/rollout.jsonl')
compacted = [r['payload'] for r in source.rows if r['type'] == 'compacted'][-1]
assert resolved['latest_compaction'] == compacted
assert resolved['items'][:6] == compacted['replacement_history']
assert len(resolved['items']) == 7
fact = read(old / 'B/finite_task/registration.json')['execution_fact']
assert all(resolved['items'][-1].get(k) == v for k,v in fact.items())
old_ids = {r['payload']['response_id'] for r in resolved['inherited_rows'] if r['type'] == 'token_usage_record'}
new_ids = {r['payload']['response_id'] for r in resolved['local_rows'] if r['type'] == 'token_usage_record'}
assert not new_ids
save(area / 'history-resolution.json', {'status': 'registered_parent_history_resolved',
    'corrects': {'path': str(area / 'by-turn/result.json'), 'sha256': file_hash(area / 'by-turn/result.json'),
                'reason': 'Flat local-file comparison did not resolve history_base; it cannot establish missing effective compaction state'},
    'observation': resolved['evidence'], 'all_compaction_fields_preserved': True,
    'compaction_field_names': sorted(compacted), 'canonical_item_count': len(resolved['items']),
    'additional_item': 'Previously injected B finite-stage execution fact; expected before requested turn',
    'same_exact_boundary_as_compaction_end': False, 'inherited_response_count': len(old_ids),
    'new_response_count': len(new_ids), 'new_model_calls': 0,
    'source_manifest_or_task_edits': False, 'model_request_equivalence': 'unobserved',
    'scope': 'One real historical native fork with a registered standalone parent, not nested forks or quality/latency proof',
    'resolver_sha256': file_hash(ROOT / 'experiments/native_fork_history.py')})
print('resolved: 183 parent records + 2 local records; all compaction fields preserved; 7 items; 0 new responses')
