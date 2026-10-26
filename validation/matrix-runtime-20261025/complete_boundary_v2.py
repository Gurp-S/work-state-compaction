"""Complete only the unexecuted continuation steps after exact-identity repair.

Previously paid compaction and selector outputs are sealed/reused, never rerun
or relabeled as a successful v1 attempt. Two new continuation responses maximum.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'src'))
from native_study_fork_session import NativeForkSession
from native_application_budget import StudyBudget
from native_incremental_candidate import prepare, admit_rendered
from native_evidence import read, save, manifest, file_hash
from wsc import WSC, Store
from wsc.contracts import Event, Usage
from wsc.quote_selection import SelectionDraft
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.publication import check_evidence

AREA = Path('D:/agent-task-runs/wsc-live-boundary-completion-20261025-v2')
OLD = Path('D:/agent-task-runs/wsc-live-boundary-qualification-20261025-v1')
BASE = Path('D:/agent-task-runs/wsc-native-application-phase-20261025-v1')
AREA.mkdir()
old_reg = read(OLD / 'registration.json')
reg = {key: old_reg[key] for key in ('workspace', 'executable', 'executable_sha256', 'model', 'effort')}
reg['initial_manifest'] = manifest(Path(reg['workspace']))
original = read(BASE / 'session/thread-start.json')['thread']
original_phase = read(BASE / 'result.json')['phase']
full_parent = read(Path('D:/agent-task-runs/wsc-boundary-transport-20261025-v1/full_parent/fork.json'))['thread']
compacted = read(OLD / 'B-before/thread-fork.json')['thread']
paths = {p['id']: p['path'] for p in (original, full_parent, compacted)}
assert file_hash(compacted['path']) == read(OLD / 'native-compact/phase-outcome.json')['rollout_sha256']
draft = read(OLD / 'selection/model-draft.json')
save(AREA / 'registration.json', dict(**reg, max_new_responses=2, max_new_total_tokens=120000,
    automatic_retries=0, purpose='complete_only_unexecuted_boundary_steps_after_exact_identity_codec_fix',
    reused=dict(compaction_phase=str(OLD / 'native-compact/phase-outcome.json'),
                generation_phase=str(OLD / 'selection-phase/phase-outcome.json'),
                draft_sha256=file_hash(OLD / 'selection/model-draft.json'), failed_v1_unchanged=True),
    source_pins={str(ROOT / 'experiments' / name): file_hash(ROOT / 'experiments' / name) for name in (
        'native_application_session.py', 'native_recursive_fork.py', 'native_study_fork_session.py', 'native_incremental_candidate.py')}))
limit = dict(max_responses=2, max_total_tokens=120000, max_seconds=180)
budget = StudyBudget({'qualification': limit}, limit)
sessions, phases = [], []
outcome = dict(status='running', paid_comparison_started=False)
try:
    old_core = WSC(Store(OLD / 'state.db', session_id='qualification-C', workspace=reg['workspace']), access=lambda *a: True)
    core = WSC(Store(AREA / 'state.db', session_id='qualification-C', workspace=reg['workspace']), access=lambda *a: True)
    core.ingest([Event(**{k:v for k,v in row.items() if k != 'seq'}) for row in old_core.capture().events])
    prepared = prepare(core, core.capture(), None, AREA / 'public-cold', lambda offered: SelectionDraft(draft, Usage()))
    operation = core.stage(prepared['view'], directory=AREA / 'exports', adapter=RecordedCodexCheckpointAdapter())
    package = admit_rendered(core.package(operation))
    check_evidence(core, package)
    save(AREA / 'package.json', package)
    save(AREA / 'continuation.json', prepared['continuation'])
    for name in ('B', 'C'):
        current = dict(reg, parent_thread_id=compacted['id'] if name == 'B' else original['id'], parent_paths=dict(paths))
        if name == 'C':
            current['before_turn_id'] = original_phase['turn_accounting']['turn_id']
        session = NativeForkSession(current, AREA / (name + '-session'))
        sessions.append(session)
        session.open()
        if name == 'C':
            session.inject(package['items'])
        ticket, granted = budget.reserve('qualification', dict(max_responses=1, max_seconds=80, max_total_tokens=60000))
        save(AREA / f'{name}-grant.json', dict(ticket=ticket, limits=granted))
        def record(value):
            save(AREA / 'journal' / f'{len(phases):03d}.json', value)
            phases.append(value)
            budget.settle(ticket, value)
        phase = session.execute_stage('独立只读续接测量：前一个协议回合的最终JSON中 ready 是什么值？输出 JSON {"previous_ready":布尔值}。',
            AREA / (name + '-phase'), granted, record)
        assert phase['usage_complete'] and phase['completed'] and phase['failure'] is None
        assert json.loads(phase['finals'][0]['text']) == {'previous_ready': True}
        session.close()
    assert {k:sessions[0].opened[k] for k in ('model','modelProvider','reasoningEffort','cwd','sandbox','approvalPolicy')} == {
        k:sessions[1].opened[k] for k in ('model','modelProvider','reasoningEffort','cwd','sandbox','approvalPolicy')}
    core.discard(operation)
    outcome.update(status='boundary_continuation_verified_with_sealed_prior_outputs',
        note='Two new continuations only. V1 remains failed; no new selection or compaction call.')
except Exception as error:
    outcome.update(status='failed_preserved', error=type(error).__name__ + ':' + str(error))
finally:
    cleanup = []
    for session in sessions:
        try:
            cleanup.append(session.close())
        except Exception as error:
            cleanup.append(dict(error=str(error)))
    outcome.update(phases=phases, budget=budget.snapshot(), cleanup=cleanup,
                   workspace_unchanged=manifest(Path(reg['workspace'])) == reg['initial_manifest'])
    save(AREA / 'result.json', outcome)
print(json.dumps(dict(status=outcome['status'], error=outcome.get('error'), new_responses=outcome['budget']['study']['responses'],
    known_new_tokens=outcome['budget']['study']['tokens'], unknown=outcome['budget']['study']['uncertain']),ensure_ascii=False))
