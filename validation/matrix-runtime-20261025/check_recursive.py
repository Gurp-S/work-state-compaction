"""Replay actual nested forks with parent tamper/cut/closure negative cases."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_recursive_fork import seal, observe
from native_fork_history import observe_fork_bytes
from native_evidence import read, save, file_hash

AREA = Path('D:/agent-task-runs/wsc-nested-fork-observation-20261025-v1')
prior = read(Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1/registration.json'))
result = read(AREA / 'result.json')
parents = {prior['parent_thread_id']: prior['parent_path']}
for entry in result['observations']:
    parents[entry['parent_id']] = entry['parent_path']
child_raw = (AREA / 'child-1.jsonl').read_bytes()
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    binding = seal(child_raw, parents, root / 'seal')
    observed = observe(child_raw, binding)
    assert observed['evidence']['depth'] == 3 and len(observed['inherited']['response_ids']) == 1
    old_binding = dict(child_sha256=binding['child_sha256'], parent=binding['parents'][0])
    try:
        observe_fork_bytes(child_raw, old_binding)
    except ValueError as error:
        old_failure = str(error)
    else:
        raise AssertionError('legacy_reader_did_not_reject_nested_parent')
    checks = ['real_three_level_ancestry_and_single_inherited_receipt']
    bad = deepcopy(binding)
    path = Path(bad['parents'][0]['path'])
    original = path.read_bytes()
    path.write_bytes(original + b'\n')
    try:
        observe(child_raw, bad)
    except ValueError:
        checks.append('tampered_parent_rejected')
    else:
        raise AssertionError('tampered_parent_accepted')
    path.write_bytes(original)
    bad = deepcopy(binding)
    bad['parents'] = bad['parents'][:-1]
    try:
        observe(child_raw, bad)
    except ValueError:
        checks.append('unclosed_ancestry_rejected')
    else:
        raise AssertionError('unclosed_ancestry_accepted')
    bad = deepcopy(binding)
    try:
        observe(child_raw.replace(b'"timestamp"', b'"timeSTAMP"', 1), bad, allow_local_append=True)
    except ValueError:
        checks.append('changed_local_prefix_rejected')
    else:
        raise AssertionError('changed_child_prefix_accepted')
save(HERE / 'recursive-checks.json', dict(passed=True, checks=checks, legacy_failure=old_failure,
    source_sha256=file_hash(ROOT / 'experiments/native_recursive_fork.py'), model_calls=0,
    scope='Replay of real zero-inference forks and sealed-source negative cases, not new model execution'))
print(dict(passed=True, checks=len(checks), legacy_failure=old_failure))
