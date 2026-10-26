"""Settle existing protocol calibration evidence; no repeated executions."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SUITE = ROOT / 'benchmarks/application-five-task-v1'
sys.path.insert(0, str(SUITE / 'acceptance'))
from runtime import manifest, save

expected = {
    'imports': {'unknown_as_zero': 'unknown_zero_isolation_and_legacy', 'duplicate_commit': 'concurrent_run_commits_once',
                'replacement_decode': 'strict_utf8_and_preview_no_commit'},
    'booking': {'stale_notification': 'cancel_invalidates_old_notification', 'duplicate_delivery': 'notification_retry_and_restart_dedup'},
    'files': {'resurrection': 'deleted_file_rejects_late_write', 'drop_history': 'history_gc_and_permanent_delete',
              'accept_conflicting_chunk': 'resume_and_chunk_identity'},
    'collaboration': {'ignore_version': 'version_conflict_and_isolation', 'partial_batch': 'batch_atomicity_and_undo_conflict',
                      'migration_reset': 'legacy_migration_twice'},
}
reviewed = []
processes = []
for task, faults in expected.items():
    area = Path('D:/agent-task-runs') / f'wsc-{task}-positive-calibration-20261025-v1'
    raw = json.loads((area / 'raw-results.json').read_text(encoding='utf8'))
    assert raw['model_calls'] == 0 and raw['production_tasks_unchanged']
    assert raw['reference_sha256'] == sha256((HERE / (task + '_service.py')).read_bytes()).hexdigest()
    originals = [run for run in raw['runs'] if run['fault'] == 'none']
    assert len(originals) == 1
    original = originals[0]['result']
    assert original['passes'] == original['checks'] and not original['full_task_qualified']
    detections = []
    for run in raw['runs']:
        path = Path(run['result_path'])
        assert sha256(path.read_bytes()).hexdigest() == run['result_sha256']
        result = json.loads(path.read_text(encoding='utf8'))
        reg = json.loads((path.parent / 'registration.json').read_text(encoding='utf8'))
        # Documentation was added after execution; bind executable bytes only.
        for name, value in reg['acceptance_manifest'].items():
            if name.endswith('.py'):
                assert sha256((SUITE / 'acceptance' / name).read_bytes()).hexdigest() == value
        assert manifest(Path(reg['workspace'])) == reg['source_manifest']
        for entry in result['outcomes']:
            receipt = json.loads((path.parent / entry['id'] / 'receipt.json').read_text(encoding='utf8'))
            starts = [e['pid'] for e in receipt['events'] if e['event'] == 'started']
            stops = [e['pid'] for e in receipt['events'] if e['event'] == 'stopped']
            assert starts == stops and starts
            processes.extend(starts)
            if not entry['passed']:
                assert receipt['failure']['type'] == 'AssertionError'
                assert not any(e.get('status', 0) >= 500 for e in receipt['events']), 'unexpected_backend_exception'
        if run['fault'] != 'none':
            target = faults[run['fault']]
            assert any(i['id'] == target and not i['passed'] for i in result['outcomes'])
            detections.append(dict(fault=run['fault'], detected_by=target, result_path=str(path), sha256=run['result_sha256']))
    reviewed.append(dict(task=task, positive_checks=original['checks'], positive_result=originals[0]['result_path'],
                         positive_sha256=originals[0]['result_sha256'], faults=detections))
assert sum(r['positive_checks'] for r in reviewed) == 27
assert sum(len(r['faults']) for r in reviewed) == 11
save(HERE / 'review.json', dict(status='four_protocol_calibrations_reviewed', tasks=reviewed,
    positive_checks=27, selected_faults_detected=11, service_starts_and_stops=len(processes),
    current_starter_manifest=manifest(SUITE / 'tasks'), model_calls=0, paid_BC_started=False,
    complete_application_qualified=False, manual_and_uncovered_edges_pending=True))
print(json.dumps(dict(positive_checks=27, selected_faults_detected=11, service_starts_and_stops=len(processes), model_calls=0)))
