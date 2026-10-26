"""Bind the producer's bounded-phase outcome to its original rollout observation."""
from datetime import datetime, timezone

from wsc.contracts import Event, digest, encode, require


def record_phase(core, snapshot, phase):
    require(snapshot.metadata['parse_complete'] and
            snapshot.metadata['sha256'] == phase['rollout_sha256'], 'phase_observation_source_changed')
    observed = datetime.now(timezone.utc).isoformat()
    public = {'kind': 'archived_native_phase_observation', 'producer': 'bounded_native_phase_runner',
        'observed_at': observed, 'thread_id': phase['thread_id'],
        'rollout_sha256': phase['rollout_sha256'], 'host_phase_completed': phase.get('completed'),
        'host_stop_reason': phase.get('failure'), 'usage_complete': phase.get('usage_complete'),
        'usage_completion_evidence': phase['usage_completion_evidence'],
        'known_response_count': phase.get('receipts', {}).get('response_count'),
        'known_usage': phase.get('receipts', {}).get('all_usage'),
        'tool_result_scope': 'Archived output presence; subsequent task-model consumption is not asserted.'}
    payload = {'observation': public, 'phase_outcome': phase}
    core.ingest([Event('native-phase:' + digest(payload), 'observation', payload,
                       text=encode(public), observed_at=observed)])
