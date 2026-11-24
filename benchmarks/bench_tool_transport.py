"""One nonstream exchange. No retry, mode escalation or loss of tool history."""
import copy
import json
import requests


def exchange(chat, messages, *, tools, tool_choice, max_tokens, base_url, model,
             max_request_chars=32000):
    payload = {'model': model, 'temperature': chat.temperature, 'max_tokens': max_tokens,
        'messages': copy.deepcopy(messages), 'thinking': {'type': 'enabled'},
        'reasoning_effort': 'low', 'tool_choice': tool_choice,
        'parallel_tool_calls': False, '_wb_strict_chat_contract': True}
    if tools:
        payload['tools'] = copy.deepcopy(tools)
    wire = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    if len(wire) > max_request_chars:
        raise ValueError('source_tool_request_budget')
    record = {'request': payload, 'request_chars': len(wire), 'status': 'requesting'}
    chat.tool_exchanges.append(record)
    chat.calls += 1
    try:
        response = requests.post(base_url + '/chat/completions',
            headers={'Authorization': 'Bearer ' + chat.key, 'Content-Type': 'application/json'},
            data=wire.encode('utf-8'), timeout=120)
        record['http_status'] = response.status_code
        record['raw_response'] = response.text
        data = response.json(); record['response'] = data
        usage = data.get('usage') or {}
        record['usage_reported'] = bool(usage)
        chat.prompt_tokens += usage.get('prompt_tokens', 0)
        chat.completion_tokens += usage.get('completion_tokens', 0)
        response.raise_for_status()
        choice = (data.get('choices') or [{}])[0]
        message, finish = choice.get('message') or {}, choice.get('finish_reason')
        meta = data.get('_wb_contract') or {}
        if not meta.get('saw_done') or not meta.get('saw_explicit_finish'):
            raise RuntimeError('source_tool_gateway_contract_missing')
        if data.get('model') != model:
            raise RuntimeError('source_tool_model_changed')
        if usage.get('completion_tokens', 0) > max_tokens:
            raise RuntimeError('source_tool_output_budget')
        calls = message.get('tool_calls') or []
        if message.get('function_call'):
            raise RuntimeError('source_tool_legacy_function_call')
        if finish == 'stop':
            if calls or not isinstance(message.get('content'), str) or not message['content'].strip():
                raise RuntimeError('source_tool_invalid_final')
        elif finish == 'tool_calls':
            if tool_choice == 'none' or not tools or not isinstance(calls, list) or not calls:
                raise RuntimeError('source_tool_unrequested_call')
        else:
            raise RuntimeError('source_tool_incomplete: ' + str(finish))
        record['status'] = 'completed'
        return data
    except Exception as error:
        record['status'] = 'failed'
        record['error'] = str(error).replace(chat.key, '[REDACTED]')
        raise
