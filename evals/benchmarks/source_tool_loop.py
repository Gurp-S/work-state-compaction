"""Opt-in model-selected source reads; no engine-generated route or repair prompts."""
import copy
import json
import os


class SourceToolRunError(RuntimeError):
    def __init__(self, message, trace):
        super().__init__(message)
        self.trace = trace


def enabled():
    return os.environ.get('WSC_CSM_SOURCE_TOOL', '0').strip().lower() in {'1', 'true', 'on'}


def prepare(service, items, rendered, *, until=None):
    # Import-free at module level for replay against a frozen older core.
    from wsc.csm.source_tools import SourceToolSession
    primary = getattr(items, 'primary', items)
    session = SourceToolSession(service, list(primary), until=until)
    if os.environ.get('WSC_CSM_SOURCE_SEARCH', '0').strip().lower() in {'1', 'true', 'on'}:
        from wsc.csm.source_search_tools import SourceSearchSession
        session = SourceSearchSession(session)
    return session, session.catalogue(rendered)


def answer(chat, service, question, items, rendered, system, *, until=None,
           user_template='Question: {question}\nMemories: {context}'):
    trace = {}
    try:
        return _run(chat, service, question, items, rendered, system,
                    until=until, user_template=user_template, trace=trace)
    except Exception as error:
        trace['error'] = str(error)
        raise SourceToolRunError(str(error), trace) from error


def _run(chat, service, question, items, rendered, system, *, until, user_template, trace):
    session, catalogue = prepare(service, items, rendered, until=until)
    context = json.dumps(catalogue, ensure_ascii=False, separators=(',', ':'))
    if len(context) > 24000:
        raise ValueError('source_tool_catalogue_budget')
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': user_template.format(question=question, context=context)}]
    trace.update({'policy': ('model-selected-evidence-tools-v2' if hasattr(session, 'definitions')
                            else 'model-selected-revision-sources-v1'), 'catalogue': catalogue,
        'limits': {'model_calls': 3, 'source_reads': 2, 'source_chars': 4000,
                   'per_call_output_tokens': 2048, 'reserved_output_tokens': 6144,
                   'total_request_chars': 72000}, 'calls': [], 'reads': []})
    submitted = 0
    seen_call_ids = set()
    for index in range(3):
        offered = getattr(session, 'can_offer', bool(session.handles)) and session.reads < session.max_reads and index < 2
        tools = (session.definitions() if hasattr(session, 'definitions') else [session.definition()]) if offered else []
        choice = 'auto' if offered else 'none'
        # Full serialization includes assistant reasoning carried across tool turns.
        approximate_request = {'messages': messages, 'tools': tools,
            'model': 'placeholder', 'temperature': 0, 'max_tokens': 2048,
            'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low',
            'tool_choice': choice, 'parallel_tool_calls': False, '_wb_strict_chat_contract': True}
        # Reserve transport model/config overhead conservatively before sending.
        request_chars = len(json.dumps(approximate_request, ensure_ascii=False, separators=(',', ':'))) + 256
        if submitted + request_chars > 72000 or request_chars > 32000:
            raise ValueError('source_tool_total_request_budget')
        submitted += request_chars
        data = chat.exchange(messages, tools=tools, tool_choice=choice, max_tokens=2048)
        message = copy.deepcopy(data['choices'][0]['message'])
        finish = data['choices'][0]['finish_reason']
        trace['calls'].append({'index': index, 'finish_reason': finish,
            'request_chars_reserved': request_chars, 'usage': data.get('usage'),
            'gateway_contract': data.get('_wb_contract')})
        if finish not in ('stop', 'tool_calls'):
            raise RuntimeError('source_tool_incomplete: ' + str(finish))
        if finish == 'stop':
            if message.get('tool_calls') or not isinstance(message.get('content'), str) or not message['content'].strip():
                raise RuntimeError('source_tool_invalid_final')
            trace.update({'source_chars': session.used_chars, 'source_reads': session.reads,
                          'request_chars_reserved': submitted})
            return {'answer': message['content'], 'source_tool': trace}
        calls = message.get('tool_calls') or []
        if not offered or not calls:
            raise RuntimeError('source_tool_batch_limit')
        oversized = len(calls) > session.max_reads - session.reads
        soft_limit = os.environ.get('WSC_CSM_SOURCE_BATCH_ERRORS','0').strip().lower() in {'1','true','on'}
        if oversized and (not soft_limit or len(calls)>16):
            raise RuntimeError('source_tool_batch_limit')
        ids = [call.get('id') for call in calls]
        if not all(isinstance(value, str) and value for value in ids) or len(set(ids)) != len(ids):
            raise RuntimeError('source_tool_call_ids_invalid')
        if seen_call_ids.intersection(ids):
            raise RuntimeError('source_tool_call_id_reused')
        seen_call_ids.update(ids)
        # No call executes unless the entire batch names an actually offered reader.
        allowed_names = {tool['function']['name'] for tool in tools}
        if any(call.get('type') != 'function' or (call.get('function') or {}).get('name') not in allowed_names for call in calls):
            raise RuntimeError('source_tool_unknown_name')
        message['role'] = 'assistant'
        messages.append(message)
        if oversized:
            body=json.dumps({'error':'source_tool_batch_limit','reads_remaining':session.max_reads-session.reads},separators=(',',':'))
            budget=session.reader if hasattr(session,'reader') else session
            if budget.used_chars+len(body)*len(calls)>budget.max_chars:
                raise RuntimeError('source_tool_character_budget')
            budget.used_chars+=len(body)*len(calls)
            for call in calls:
                messages.append({'role':'tool','tool_call_id':call['id'],'content':body})
                trace['reads'].append({'call_id':call['id'],'arguments':call['function'].get('arguments'),
                    'executed':False,'result':json.loads(body)})
            continue
        for call in calls:
            function = call['function']
            body = session.execute(function['name'], function.get('arguments'))
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': body})
            trace['reads'].append({'call_id': call['id'], 'arguments': function.get('arguments'), 'result': json.loads(body)})
    raise RuntimeError('source_tool_model_call_limit')
