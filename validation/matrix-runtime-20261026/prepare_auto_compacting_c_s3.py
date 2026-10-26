"""Preserve the exact old S3 delta, restore S2 in place, reuse sealed selection."""
from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_application_session import NativeApplicationSession
from native_host_controls import settings
from wsc import WSC, Store
from wsc.publication import check_evidence

OLD = Path('D:/agent-task-runs/wsc-a3-dev-C-calibrated-20261026-v1')
POLICY = Path('D:/agent-task-runs/wsc-c-auto-compaction-policy-20261026-v1')
OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-auto-compaction-20261026-v1')
OUT.mkdir(exist_ok=False)
prepared = read(OLD / 'prepared.json')
plan = read(POLICY / 's2-restore-plan.json')
reg = prepared['registration']
work = Path(reg['workspace']).resolve()
assert work == Path(plan['workspace']).resolve()
assert work == Path('D:/agent-task-runs/wsc-paired-evaluation-admission-20261026-v1/C/workspace').resolve()
measurer = NativeApplicationSession(reg, OUT / 'inspection-only')
before = measurer.source_manifest()
assert before == read(OLD / 'result.json')['source_manifest_after'], 'old_S3_source_changed'
assert read(OLD / 'result.json')['cleanup']['empty_confirmed']
expected = reg['initial_manifest']
assert sorted(set(before) - set(expected)) == plan['extra'] and not plan['missing']
assert {name for name in before if name in expected and before[name] != expected[name]} == {r['path'] for r in plan['changed']}
save(OUT / 'retained-S3-manifest.json', before)
archive = OUT / 'retained-S3-six-source-files.zip'
with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
    for entry in plan['changed']:
        path = work / entry['path']
        assert file_hash(path) == entry['current_sha256']
        assert file_hash(Path(entry['restore_source'])) == entry['expected_sha256']
        zipped.write(path, entry['path'])
with zipfile.ZipFile(archive) as zipped:
    assert zipped.testzip() is None
    from hashlib import sha256
    assert all(sha256(zipped.read(r['path'])).hexdigest() == r['current_sha256'] for r in plan['changed'])
private = [work / 'gui/node_modules', work / '.wsc-runtime/browsers']
identities = {str(path): path.stat().st_ino for path in private}
assert all(path.is_dir() and not path.lstat().st_file_attributes & 1024 for path in private)
retained = (OUT / 'retained-S3-validation').resolve()
retained.mkdir()
roots = sorted({'/'.join(name.split('/')[:2]) for name in plan['extra']})
moves = []
for key in roots:
    source = (work / key).resolve()
    target = (retained / Path(key).name).resolve()
    assert source.is_relative_to(work) and target.is_relative_to(retained)
    assert source.is_dir() and not source.lstat().st_file_attributes & 1024 and not target.exists()
    assert not any(name == key or name.startswith(key + '/') for name in expected)
    moves.append(dict(source=str(source), target=str(target), original_prefix=key))
save(OUT / 'retained-S3-move-plan.json', moves)
for move in moves:
    Path(move['source']).rename(Path(move['target']))
for name in plan['extra']:
    move = next(m for m in moves if name.startswith(m['original_prefix'] + '/'))
    relocated = Path(move['target']) / Path(name).relative_to(move['original_prefix'])
    assert file_hash(relocated) == before[name]
for entry in plan['changed']:
    (work / entry['path']).write_bytes(Path(entry['restore_source']).read_bytes())
assert measurer.source_manifest() == expected, 'restored_S2_manifest_mismatch'
assert all(path.stat().st_ino == identities[str(path)] for path in private)
save(OUT / 'S2-restoration.json', dict(exact_initial_manifest=True, original_file_count=len(expected),
    changed_source_files=len(plan['changed']), retained_extra_files=len(plan['extra']), retained_directories=moves,
    old_code_archive=str(archive), old_code_archive_sha256=file_hash(archive), private_directory_identities=identities,
    source_and_dependency_copies=0, old_result_sha256=file_hash(OLD / 'result.json'), model_calls=0))
source_db = OLD / 'state.db'
db_hash = file_hash(source_db)
with closing(sqlite3.connect('file:' + str(source_db) + '?mode=ro', uri=True)) as source:
    with closing(sqlite3.connect(OUT / 'state.db')) as target:
        source.backup(target)
assert file_hash(source_db) == db_hash
core = WSC(Store(OUT / 'state.db', session_id='a3/calibrated-selection-v1/C', workspace=reg['workspace']), access=lambda *args: True)
package = read(Path(prepared['package']))
check_evidence(core, package)
save(OUT / 'package.json', package)
assert file_hash(OUT / 'package.json') == prepared['package_sha256']
reg = {**reg, 'study_arm': 'C', 'native_c_auto_compaction': read(POLICY / 'registration.json')['native_c_auto_compaction']}
assert settings(reg)[-1] == 'model_auto_compact_token_limit=96000'
save(OUT / 'prepared.json', {**prepared, 'registration': reg, 'package': str(OUT / 'package.json'),
    'budget_parent': str(POLICY), 'prior_development': str(OLD), 'selection_regenerated': False,
    'scope': 'Same exact S2, original S3 and calibrated WSC package; C-only native internal threshold96000; not formal B/C'})
save(OUT / 'policy-adoption.json', read(OLD / 'policy-adoption.json'))
save(OUT / 'verification-plan.json', {**read(OLD / 'verification-plan.json'),
    'hypothesis': 'Same-session native earlier compaction may reduce cumulative context growth without losing task or tool state',
    'additional_audit': ['actual_in_turn_compaction_and_receipts', 'post_compaction_actions',
        'all_cached_uncached_output_and_compaction_spend', 'scope_preservation_after_native_summary'],
    'timing_is_not_WSC_semantic_benefit': True, 'automatic_retries': 0})
print(dict(restored_exact_S2=True, retained_S3=True, selection_regenerated=False, model_calls=0))
