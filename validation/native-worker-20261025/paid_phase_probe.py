"""One paid transport/receipt smoke on the new binary, not a B/C task repeat."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_session import NativeApplicationSession
from native_evidence import save, manifest, file_hash

AREA = Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1')
AREA.mkdir()
work = AREA / 'workspace'
work.mkdir()
(work / 'README.md').write_text('Read-only protocol observation fixture.\n', encoding='utf8')
initial = manifest(work)
exe = Path('C:/Users/48522/AppData/Local/OpenAI/Codex/bin/2993767bd1dfb009/codex.exe')
reg = dict(workspace=str(work), initial_manifest=initial, executable=str(exe), executable_sha256=file_hash(exe),
           model='gpt-6-luna', effort='max', purpose='one_response_new_native_phase_transport_probe',
           inference_responses_allowed=1, automatic_retries=0,
           budget=dict(max_responses=1, max_seconds=90, max_total_tokens=60000),
           request='这是一条独立的只读协议测量。直接输出 JSON {"ready":true}。',
           source_pins={str(ROOT / 'experiments' / name): file_hash(ROOT / 'experiments' / name)
                        for name in ('native_application_session.py', 'native_owned_process.py', 'native_rpc.py',
                                     'native_turn_accounting.py', 'native_phase_budget.py')},
           cash=None, comparison_result=False)
save(AREA / 'registration.json', reg)
session = NativeApplicationSession(reg, AREA / 'session')
journal = []


def record(outcome):
    save(AREA / 'journal' / f'{len(journal):03d}.json', outcome)
    journal.append(outcome)


result = dict(status='running', paid_comparison_started=False)
try:
    session.open()
    outcome = session.execute_stage(reg['request'], AREA / 'phase', reg['budget'], record)
    result.update(status='native_phase_executed_review_pending', phase=outcome, journal_entries=len(journal))
except Exception as error:
    result.update(status='failed', error=type(error).__name__ + ':' + str(error), journal_entries=len(journal))
finally:
    result['cleanup'] = session.close()
    result['workspace_unchanged'] = manifest(work) == initial
    save(AREA / 'result.json', result)
outcome = result.get('phase', {})
print(json.dumps(dict(status=result['status'], completed=outcome.get('completed'), failure=outcome.get('failure'),
    usage_complete=outcome.get('usage_complete'), receipts=outcome.get('receipts'),
    accounting_error=outcome.get('accounting_error'), seconds=outcome.get('seconds'),
    workspace_unchanged=result['workspace_unchanged']), ensure_ascii=False))
