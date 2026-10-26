"""Explicit fork admission and incremental accounting; legacy routes unchanged."""
from pathlib import Path
from hashlib import sha256
import json

from native_evidence import digest, import_evidence, manifest
from native_fork_history import observe_fork_bytes
from native_task_checks import require
from native_turn_accounting import account_turn, admit_resumed_turn, vector


def fork_baseline(before_raw, binding, *, thread_id):
    observation = observe_fork_bytes(before_raw, binding)
    local, parent = observation['local_rows'], observation['inherited_rows']
    meta = [r['payload'] for r in local if r['type'] == 'session_meta']
    require(len(meta) == 1 and meta[0]['id'] == thread_id, 'fork_phase_thread_mismatch')
    paid = [r['payload'] for r in parent if r['type'] == 'token_usage_record']
    counts = [r['payload'].get('info') for r in parent if r['type'] == 'event_msg'
              and r['payload'].get('type') == 'token_count']
    require(paid and counts and vector(paid[-1].get('thread_token_usage'))
            and vector((counts[-1] or {}).get('total_token_usage'))
            and all(p.get('thread_id') == binding['parent']['thread_id']
                    and isinstance(p.get('response_id'), str) and p['response_id'] for p in paid),
            'fork_phase_inherited_counter_unknown')
    local_paid = [r['payload'] for r in local if r['type'] == 'token_usage_record']
    if local_paid:
        admit_resumed_turn(before_raw, thread_id=thread_id)
    require(not any(p.get('response_id') in {p['response_id'] for p in paid} for p in local_paid),
            'fork_phase_parent_response_reused')
    return {'inherited': {'thread': paid[-1]['thread_token_usage'],
                         'display': counts[-1]['total_token_usage'],
                         'response_ids': sorted({p['response_id'] for p in paid})},
            'local_response_ids': [p['response_id'] for p in local_paid],
            'history_evidence': observation['evidence']}


def account_fork_turn(before_raw, after_raw, *, binding, thread_id, turn_id):
    baseline = fork_baseline(before_raw, binding, thread_id=thread_id)
    return account_admitted_fork_turn(before_raw, after_raw, baseline=baseline,
                                      thread_id=thread_id, turn_id=turn_id)


def account_admitted_fork_turn(before_raw, after_raw, *, baseline, thread_id, turn_id):
    """Settle against captured admission, retaining cost if parent later changes.

    baseline is the in-process fork_baseline result, not a caller-supplied claim.
    Final history reconstruction separately rechecks the registered parent.
    """
    require(baseline['history_evidence']['child_sha256'] == sha256(before_raw).hexdigest(),
            'fork_phase_admission_snapshot_changed')
    proof = account_turn(before_raw, after_raw, thread_id=thread_id, turn_id=turn_id,
                         inherited=baseline['inherited'])
    proof.update(scope='registered_fork_append_only_single_turn', fork_baseline=baseline)
    return proof


def verify_fork_execution(reg, opened, current, item):
    require(reg.get('accounting_scope') == 'fork_append_only_turn' and reg.get('fork_history_binding'),
            'fork_phase_registration_missing')
    raw = Path(opened['thread']['path']).read_bytes()
    observation = observe_fork_bytes(raw, reg['fork_history_binding'])
    local = observation['local_rows']
    meta = next(r['payload'] for r in local if r['type'] == 'session_meta')
    require(meta['id'] == opened['thread']['id'], 'fork_phase_thread_mismatch')
    settings = [r['payload'] for r in local if r['type'] == 'event_msg'
                and r['payload'].get('type') == 'thread_settings_applied']
    require(settings and settings[-1].get('thread_id') == opened['thread']['id'],
            'fork_phase_current_settings_missing')
    settings = settings[-1]['thread_settings']
    require(Path(settings['cwd']).resolve() == current.resolve()
            and Path(opened['cwd']).resolve() == current.resolve(), 'fork_phase_runtime_workspace_mismatch')
    require(settings.get('model') == opened.get('model') == reg['model']
            and settings.get('reasoning_effort') == opened.get('reasoningEffort') == reg['effort'],
            'fork_phase_model_configuration_mismatch')
    fact = json.loads(item['content'][0]['text'])
    require(fact.get('current_file_manifest_sha256') == digest(manifest(current)),
            'fork_phase_workspace_manifest_changed')
    require(observation['items'] and import_evidence(observation['items'][-1:], [item])['matched'],
            'fork_phase_execution_fact_not_current_tail')
    # A fact merely inherited from an older parent cannot establish this launch.
    local_items = [r['payload'] for r in local if r['type'] == 'response_item']
    require(local_items and import_evidence(local_items[-1:], [item])['matched'],
            'fork_phase_execution_fact_not_local')
    return observation['evidence']
