"""Freeze selection policy, declared boundaries and numeric budgets, not launch approval."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash, manifest
from native_incremental_candidate import POLICY

native = read(ROOT / 'validation/native-worker-20261025/review.json')
checks = read(HERE / 'checks.json')
assert checks['passed'] and all(file_hash(path) == value for path, value in checks['source_pins'].items())
candidate = dict(**POLICY, generation_model=native['observed_model'], generation_effort=native['effort'],
    implementation=dict(path=str(ROOT / 'experiments/native_incremental_candidate.py'),
                        sha256=file_hash(ROOT / 'experiments/native_incremental_candidate.py')),
    core_manifest=manifest(ROOT / 'src'), generator_sandbox='read-only',
    prior_state='Exact source-bound cut, explicitly selected previous record revisions and previous excerpt identities',
    event_ingestion='Original business-stage delta only; imported checkpoint/bootstrap and generation answers are not re-ingested as new business history',
    source_contract='New public text plus all old public-source identity/read handles; prior excerpt text selected explicitly',
    current_applicability='Model judgment; old observation time and source version remain historical',
    package_adapter='codex_recorded_checkpoint_v1',
    failure_policy='No fallback to whole messages, no silent truncation, no repair retry; retain usage and artifact',
    status='selection_policy_frozen_native_boundary_integration_pending')
budgets = dict(ordinary_phase=dict(max_responses=32, max_seconds=600, max_total_tokens=750000),
    boundary_phase=dict(max_responses=12, max_seconds=180, max_total_tokens=400000),
    per_arm=dict(max_responses=120, max_seconds=2700, max_total_tokens=6000000),
    study=dict(max_responses=3600, max_seconds=28800, max_total_tokens=180000000),
    coverage='All business, native compaction and WSC selection responses count against the same arm and study ledger',
    token_scope='Includes cached input; admission/receipt-boundary caps, not provider-side hard token limits',
    overshoot='Entire observed response counts; no subsequent call after the arm is stopped',
    uncertainty='Known receipts retained; unknown total freezes new study admission',
    infrastructure_replacement_pairs=0, automatic_retries=0, cash=None,
    wall_scope='Study model scheduler starts after prepared inputs; record preparation and external quality time separately',
    review_time_policy='Full UI review evidence is retained; absent review remains unknown and never auto-passed')
boundaries = dict(after_stages=[2, 4, 6], scope='Same three declared manual boundaries in all repetitions; automatic native compaction also counted',
    B='Unmodified native compactor; continue from its exact native checkpoint via native fork',
    C='Registered incremental selection; native fork of the sealed initial bootstrap, followed by exact checkpoint item import',
    transport='Both arms use native fork at boundaries; no raw copying of opaque compaction items into a fresh thread',
    controls='Frozen model/tool/runtime; unchanged workspace; normalize only registered per-arm resource paths and native transport IDs',
    admission='Observe fork provenance, effective history, settings, source seals and imported item equality before next model call',
    reject='Stop on mismatched host controls, unknown accounting or incomplete package; no repeated admission attempts',
    native_wire_equivalence_proven=False,
    installation='Native accepted import and saved-history audit; no fabricated HostReceipt or claim of full transactional HostPort')
registration = dict(kind='five_task_study_conditions_v1', frozen_parts=['selection_policy', 'boundary_protocol', 'numeric_budgets'],
    model=native['observed_model'], effort=native['effort'], executable=native['current_executable'],
    candidate=candidate, budgets=budgets, boundaries=boundaries,
    tasks=5, pairs_per_task=3, pairs=15, trajectories=30, parallel_pairs=2, parallel_trajectories=4,
    launch_qualified=False, paid_model_experiment_started=False,
    launch_gaps=['Native fork/import callback and matched host admission need live zero-inference qualification',
                 'Candidate generation/read-only client must be wired and qualified',
                 'Cumulative ledger and final quality validator must be connected to full matrix workers',
                 'A3 private dependency copy/materialization and grader adapters need wiring'],
    inference_this_registration=0)
save(HERE / 'study-conditions-v1.json', registration)
print(json.dumps(dict(candidate=POLICY['id'], boundaries=[2,4,6], per_arm_max_total_tokens=6000000,
    study_max_total_tokens=180000000, launch_qualified=False, model_calls=0)))
