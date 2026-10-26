"""Zero-inference import and cold-file access of the exact archived C selection."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash
from native_study_fork_session import NativeForkSession
from native_typed_content import dependencies
from wsc import WSC, Store
import native_cold_access

AREA = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT = AREA / 'indexed-native-import-v1'
OUT.mkdir(exist_ok=False)
payload = read(AREA / 'staged/payload-C.json')
reg = payload['registration']
prefix = payload['common_prefix']
reg = {**reg, 'parent_thread_id': prefix['reset_parent_thread_id'],
    'before_turn_id': prefix['reset_before_turn_id']}
package = read(AREA / 'indexed-view-replay-v2/package.json')
session = NativeForkSession(reg, OUT / 'receiver')
core = WSC(Store(AREA / 'arms/C/output/wsc.db', session_id='a3/sharedS2/C', workspace=reg['workspace']), access=lambda *a: True)
try:
    session.open()
    proof = session.inject(package['items'])
    native_cold_access.package(session, package, OUT / 'cold-access', dependencies(core))
    result = dict(exact_import=proof, cold_access=read(OUT / 'cold-access/execution.json'),
        source_manifest_unchanged=session.source_manifest() == reg['initial_manifest'],
        draft_sha256=file_hash(AREA / 'arms/C/output/S2-generation/model-draft.json'),
        package_sha256=file_hash(AREA / 'indexed-view-replay-v2/package.json'), model_calls=0,
        scope='Native import and read-only hash verification only; no business continuation or benefit proof')
finally:
    cleanup = session.close()
result['cleanup'] = cleanup
assert cleanup['empty_confirmed'] and result['source_manifest_unchanged']
save(OUT / 'result.json', result)
print(result)
