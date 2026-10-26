"""Read-only replay of observed native bootstrap boundaries; no runtime adapter.

Writes a counterfactual item list, never an installable package or model result.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'experiments')]
from native_evidence import read, save, digest, import_evidence, file_hash
from native_rollout_snapshot import capture_rollout
from wsc.contracts import encode


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def normalized(item):
    return {key: item[key] for key in ('type', 'role', 'content') if key in item}


def source_boundary(items, admission, registration, phase):
    require(admission['thread_id'] == phase['thread_id'] and admission['response_count'] == 0,
            'source_initial_admission_mismatch')
    require(registration['accounting_scope'] == 'fresh_single_turn', 'source_turn_scope_unsupported')
    control = [registration['execution_fact']]
    require(admission['controls_sha256'] == digest(control), 'source_control_binding_changed')
    evidence = import_evidence(items, control)
    require(evidence['matched'], 'source_execution_fact_missing')
    prefix = items[:evidence['start_ordinal']]
    require(prefix and digest(prefix) == admission['prefix_sha256'], 'source_prefix_changed')
    require([normalized(item) for item in prefix] == admission['host']['bootstrap_messages'],
            'source_bootstrap_observation_changed')
    require(all(item.get('type') == 'message' and item.get('role') in {'system', 'developer', 'user'}
                for item in prefix), 'source_bootstrap_contains_task_activity')
    return prefix


def project(items, prefix, source_ids, locators, target_admission):
    # User-role bootstrap text is never retired merely because a newer host is
    # available. This replay requires byte-value coverage by that observed host.
    current = target_admission['host']['bootstrap_messages']
    require(all(normalized(item) in current for item in prefix if item['role'] == 'user'),
            'host_user_control_coverage_missing')
    require(items[:len(prefix)] == prefix, 'checkpoint_prefix_does_not_match_source')
    result = deepcopy(items[len(prefix):])
    state_items = []
    for index, item in enumerate(result):
        if item.get('type') != 'message' or item.get('role') != 'assistant':
            continue
        content = item.get('content', [])
        if len(content) != 1 or not isinstance(content[0].get('text'), str):
            continue
        try:
            value = json.loads(content[0]['text'])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get('kind') == 'working_state':
            state_items.append((index, value))
    require(len(state_items) == 1, 'working_state_ambiguous')
    index, state = state_items[0]
    state['historical_host_context'] = {
        'kind': 'archived_native_startup_observation',
        'sources': [{'source_id': key, 'path': locators[key]['file_path'],
                     'sha256': locators[key]['sha256'], 'observed_at': locators[key]['observed_at']}
                    for key in source_ids]}
    result[index]['content'][0]['text'] = encode(state)
    return result, index


def main(source, target, output):
    require(not output.exists(), 'audit_output_exists')
    output.mkdir(parents=True)
    paths = [source / 'source_task/admission.json', source / 'source_task/registration.json',
             source / 'source_task/phase-outcome.json', source / 'native-rollout-archive/source.jsonl',
             target / 'expanded_task/admission.json', target / 'expanded_task/rollout.jsonl',
             target / 'checkpoint/package.json']
    before = {str(p): file_hash(p) for p in paths}
    admission, registration, phase = [read(p) for p in paths[:3]]
    snapshot = capture_rollout(paths[3])
    require(snapshot.metadata['parse_complete'] and snapshot.metadata['sha256'] == phase['rollout_sha256'],
            'source_archive_changed')
    source_items = [r['payload'] for r in snapshot.rows if r['type'] == 'response_item']
    prefix = source_boundary(source_items, admission, registration, phase)
    package, current = read(paths[-1]), read(paths[-3])
    actual = [r['payload'] for r in capture_rollout(paths[-2]).rows if r['type'] == 'response_item']
    supplied = import_evidence(actual, package['items'])
    require(supplied['matched'] and digest(actual[:supplied['start_ordinal']]) == current['prefix_sha256'],
            'target_native_prefix_changed')
    require([normalized(p) for p in actual[:supplied['start_ordinal']]] == current['host']['bootstrap_messages'],
            'target_bootstrap_observation_changed')
    keys = [f"native:{phase['thread_id']}:{index}:{digest(item)}" for index, item in enumerate(prefix)]
    for key, item in zip(keys, prefix):
        evidence = package['evidence'][key]
        require(file_hash(evidence['file_path']) == evidence['sha256'] and read(evidence['file_path']) == item,
                'cold_bootstrap_evidence_changed')
    projected, state_index = project(package['items'], prefix, keys, package['evidence'], current)
    original_tail = deepcopy(package['items'][len(prefix):])
    restored = deepcopy(projected)
    state = json.loads(restored[state_index]['content'][0]['text'])
    state.pop('historical_host_context')
    original_state = json.loads(original_tail[state_index]['content'][0]['text'])
    require(state == original_state, 'task_state_changed')
    restored[state_index] = original_tail[state_index]
    require(restored == original_tail, 'task_message_changed')
    guards = []
    bad = deepcopy(admission); bad['prefix_sha256'] = 'changed'
    try:
        source_boundary(source_items, bad, registration, phase)
    except ValueError as exc:
        require(str(exc) == 'source_prefix_changed', 'unexpected_guard_result'); guards.append(str(exc))
    bad = deepcopy(current)
    bad['host']['bootstrap_messages'] = [p for p in bad['host']['bootstrap_messages'] if p['role'] != 'user']
    try:
        project(package['items'], prefix, keys, package['evidence'], bad)
    except ValueError as exc:
        require(str(exc) == 'host_user_control_coverage_missing', 'unexpected_guard_result'); guards.append(str(exc))
    require(len(guards) == 2, 'counterexample_was_accepted')
    require(before == {str(p): file_hash(p) for p in paths}, 'audit_changed_original_artifacts')
    exact = [i for i, p in enumerate(prefix) if normalized(p) in current['host']['bootstrap_messages']]
    old_bytes, new_bytes = len(encode(package['items']).encode()), len(encode(projected).encode())
    report = {'scope': 'counterfactual serialization only; no runtime adapter, installation, inference, token savings or causal quality proof',
        'source_prefix_records': len(prefix), 'source_prefix_ids': keys, 'exactly_repeated_in_target_host': exact,
        'changed_host_prefix_indices': [i for i in range(len(prefix)) if i not in exact],
        'user_bootstrap_coverage_verified': True, 'original_bootstrap_cold_values_verified': True,
        'task_tail_messages_and_state_unchanged': True, 'before_item_bytes': old_bytes,
        'candidate_item_bytes': new_bytes, 'item_byte_reduction_percent': 100 * (old_bytes-new_bytes) / old_bytes,
        'counterexamples_rejected': guards, 'input_sha256': before, 'new_model_calls': 0}
    save(output / 'audit.json', report)
    save(output / 'counterfactual-items.json', projected)
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_prefix_ids','input_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main(*(Path(value).resolve() for value in sys.argv[1:]))
