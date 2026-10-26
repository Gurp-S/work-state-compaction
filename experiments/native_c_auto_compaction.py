"""Opt-in C session policy; native compaction timing is not WSC semantic gain."""
from pathlib import Path
from native_evidence import read, file_hash


def startup_flags(registration):
    if 'native_c_auto_compaction' not in registration:
        return []
    def require(ok, reason):
        if not ok:
            raise ValueError(reason)
    require(registration.get('study_arm') == 'C', 'auto_compaction_requires_C_arm')
    spec = registration['native_c_auto_compaction']
    require(isinstance(spec, dict) and set(spec) == {'token_limit', 'qualification_path', 'qualification_sha256'},
        'auto_compaction_policy_invalid')
    require(type(spec['token_limit']) is int and spec['token_limit'] == 96000, 'auto_compaction_limit_unregistered')
    path = Path(spec['qualification_path'])
    require(path.is_absolute() and file_hash(path) == spec['qualification_sha256'], 'auto_compaction_qualification_changed')
    proof = read(path)
    require(proof.get('format') == 'native_post_compaction_access_v1' and all(proof.get(key) is True for key in
        ('same_service_and_thread', 'in_turn_compaction_receipt_bound', 'post_compaction_tool_access',
         'same_pid_nonce_heartbeat_observed', 'all_local_usage_complete', 'cleanup_empty')),
        'auto_compaction_capability_unqualified')
    require(all(registration.get(key) == proof['native_session'].get(key) for key in
        ('executable_sha256', 'model', 'effort', 'host_feature_overrides')), 'auto_compaction_native_binding_changed')
    require(all(file_hash(path.parent / name) == expected for name, expected in proof['inputs_sha256'].items()),
        'auto_compaction_capability_source_changed')
    # 96000 is the registered application candidate, not a proven optimum or
    # a claim that the 32000 protocol fixture qualified application delivery.
    return ['model_auto_compact_token_limit=96000']
