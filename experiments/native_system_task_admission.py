"""Explicit system-blackbox admission; unknown capacity is never verified True."""
from hashlib import sha256
from wsc.contracts import require


def admit(receiver, request, output_schema, callback):
    require(callable(callback), 'task_system_admission_missing')
    value = callback(receiver.session, request, output_schema)
    require(isinstance(value, dict) and value.get('comparison') == 'system_blackbox'
            and value.get('capacity_status') == 'unobserved'
            and value.get('request_input_tokens') is None, 'task_system_admission_invalid')
    require(value.get('thread_id') == receiver.owner and value.get('workspace') == receiver.workspace
            and value.get('request_sha256') == sha256(request.encode('utf-8')).hexdigest()
            and value.get('source_digest') == receiver.handler.reader.snapshot_binding['source_digest'],
            'task_system_admission_binding_changed')
    require(type(value.get('budget_ticket')) is str and bool(value['budget_ticket'])
            and isinstance(value.get('limits'), dict) and set(value['limits']) == {
                'max_total_tokens', 'max_responses', 'max_seconds'}
            and all(type(v) is int and v > 0 for v in value['limits'].values()), 'task_system_budget_unbound')
    return value
