"""One bounded live qualification of compact/fork/select/import/continuation.

Uses the existing minimal protocol history, never a new application trajectory.
All new responses count as preparation, including failed qualification work.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'src'))
from native_application_session import NativeApplicationSession
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_incremental_candidate import prepare, admit_rendered
from native_incremental_generation import generate
from native_evidence import read, save, manifest, file_hash
from native_rollout_snapshot import capture_rollout, parse_rollout
from wsc import WSC, Store
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.publication import check_evidence

AREA = Path('D:/agent-task-runs/wsc-live-boundary-qualification-20261025-v1')
OLD = Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1')
AREA.mkdir()
old_reg, old_phase = read(OLD / 'registration.json'), read(OLD / 'result.json')['phase']
parent = read(OLD / 'session/thread-start.json')['thread']
fork = read(Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1/full_parent/fork.json'))['thread']
initial = manifest(Path(old_reg['workspace']))
limits = dict(max_total_tokens=180000, max_responses=5, max_seconds=300)
reg = dict(workspace=old_reg['workspace'], initial_manifest=initial, executable=old_reg['executable'],
    executable_sha256=old_reg['executable_sha256'], model=old_reg['model'], effort=old_reg['effort'])
paths = {parent['id']: parent['path'], fork['id']: fork['path']}
save(AREA / 'registration.json', dict(**reg, purpose='live_boundary_transport_and_accounting_qualification',
    total_limits=limits, phase_response_limits=dict(compact=1, selection=2, B_continue=1, C_continue=1),
    source_parent_sha256=file_hash(parent['path']), automatic_retries=0, paid_comparison=False,
    pins={str(p): file_hash(p) for p in [ROOT / 'experiments' / name for name in (
        'native_application_session.py','native_study_fork_session.py','native_recursive_fork.py',
        'native_incremental_candidate.py','native_incremental_generation.py','native_application_budget.py')]}))
budget = StudyBudget({'qualification': limits}, limits)
sessions, phases = [], []


def open_session(cls, name, **extra):
    current = {**reg, 'initial_manifest': manifest(Path(reg['workspace'])), **extra}
    session = cls(current, AREA / name)
    sessions.append(session)
    session.open()
    paths[session.opened['thread']['id']] = session.opened['thread']['path']
    return session


def run(session, name, request, responses=1, **options):
    ticket, granted = budget.reserve('qualification', dict(max_total_tokens=90000, max_responses=responses, max_seconds=90))
    save(AREA / f'{name}-grant.json', dict(ticket=ticket, limits=granted, ledger=budget.snapshot()))
    def record(value):
        save(AREA / 'journal' / f'{len(phases):03d}.json', value)
        phases.append(value)
        settled = budget.settle(ticket, value)
        save(AREA / f'{name}-settled.json', dict(result=settled, ledger=budget.snapshot()))
    result = session.execute_stage(request, AREA / name, granted, record, **options)
    if not result.get('usage_complete') or not result.get('completed') or result.get('failure'):
        raise ValueError('live_qualification_phase_not_complete:' + name + ':' + str(result.get('failure')) + ':' + str(result.get('accounting_error')))
    return result


outcome = dict(status='running', paid_comparison_started=False)
try:
    B = open_session(NativeForkSession, 'B-before', parent_thread_id=fork['id'], parent_paths=dict(paths))
    compacted = run(B, 'native-compact', 'native_compaction', compact=True)
    assert len(compacted['receipts']['compactor_response_ids']) == 1
    B.close()

    source = capture_rollout(OLD / 'phase/rollout.jsonl')
    before = parse_rollout((OLD / 'session/opened.jsonl').read_bytes())
    rows = source.rows[len(before.rows):]
    source_rows = [row for row in rows if row['type'] == 'response_item']
    core = WSC(Store(AREA / 'state.db', session_id='qualification-C', workspace=reg['workspace']), access=lambda *args: True)
    batch = CodexCheckpointAdapter().import_items([row['payload'] for row in source_rows], thread_id=parent['id'],
        observed_at=[row.get('timestamp') for row in source_rows])
    core.ingest(batch)
    core.presented('source-probe-result', tuple(e.id for e in batch if e.kind == 'result'), receiver='qualification-selector')
    selector = open_session(NativeApplicationSession, 'selector', sandbox='read-only')
    def execute(request, schema):
        phase = run(selector, 'selection-phase', json.dumps(request, ensure_ascii=False, sort_keys=True),
                    responses=2, output_schema=schema)
        return phase, AREA / 'selection-phase/rollout.jsonl'
    prepared = prepare(core, core.capture(), None, AREA / 'public-cold',
        lambda offered: generate(offered, execute, AREA / 'selection'))
    selector.close()
    operation = core.stage(prepared['view'], directory=AREA / 'exports', adapter=RecordedCodexCheckpointAdapter())
    package = admit_rendered(core.package(operation))
    check_evidence(core, package)
    save(AREA / 'package.json', package)
    save(AREA / 'continuation.json', prepared['continuation'])

    B2 = open_session(NativeForkSession, 'B-after', parent_thread_id=B.opened['thread']['id'], parent_paths=dict(paths))
    C = open_session(NativeForkSession, 'C-after', parent_thread_id=parent['id'], parent_paths=dict(paths),
        before_turn_id=old_phase['turn_accounting']['turn_id'])
    assert {k:B2.opened[k] for k in ('model','modelProvider','reasoningEffort','cwd','sandbox','approvalPolicy')} == {
        k:C.opened[k] for k in ('model','modelProvider','reasoningEffort','cwd','sandbox','approvalPolicy')}
    C.inject(package['items'])
    request = '独立只读续接测量：前一个协议回合的最终JSON中 ready 是什么值？输出 JSON {"previous_ready":布尔值}。'
    for name, session in [('B-continuation', B2), ('C-continuation', C)]:
        phase = run(session, name, request)
        assert json.loads(phase['finals'][0]['text']) == {'previous_ready': True}
    # Export/install audit only: no fabricated transactional core HostReceipt.
    core.discard(operation)
    outcome.update(status='compact_select_fork_import_and_continuation_verified',
        rendered_package_bytes=len(json.dumps(package['items'],ensure_ascii=False).encode()),
        scope='One small live boundary; no full application or three-boundary benefit proof')
except Exception as error:
    outcome.update(status='failed_preserved', error=type(error).__name__ + ':' + str(error))
finally:
    cleanups = []
    for session in sessions:
        try:
            cleanups.append(session.close())
        except Exception as error:
            cleanups.append(dict(error=str(error)))
    outcome.update(phases=phases, budget=budget.snapshot(), cleanup=cleanups,
                   workspace_unchanged=manifest(Path(reg['workspace'])) == initial)
    save(AREA / 'result.json', outcome)
print(json.dumps(dict(status=outcome['status'], error=outcome.get('error'), responses=outcome['budget']['study']['responses'],
    known_total_tokens=outcome['budget']['study']['tokens'], unknown=outcome['budget']['study']['uncertain'],
    phases=[dict(completed=p['completed'], failure=p['failure'], complete=p.get('usage_complete'),
        accounting_error=p.get('accounting_error'), seconds=p['seconds']) for p in phases]), ensure_ascii=False))
