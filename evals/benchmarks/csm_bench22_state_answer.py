"""Optional deterministic publication of answer claims from offered state."""
import json


_OFFERABLE = {'CURRENT_CONFIRMED', 'HISTORICAL', 'DUE', 'DEADLINE_DATE', 'COMMITMENT_STATE',
              'CONFLICT_UNRESOLVED'}
_UNKNOWN = '现有记忆状态无法确认这件事。'


def offer_state_answer(question, state_items):
    offered = {f's{index}': item['text'] for index, item in enumerate(state_items)
               if item['kind'] in _OFFERABLE and item.get('source_turns')}
    prompt = {'question': question, 'state_choices': offered,
              'response_schema': {'state_refs': 'zero to four distinct keys from state_choices',
                                  'empty_state_refs': 'no publishable answer from supplied state'}}
    return offered, json.dumps(prompt, ensure_ascii=False)


def publish_state_answer(response, offered):
    def reject(reason):
        return {'status': reason, 'state_refs': [], 'answer': _UNKNOWN}

    if response is None and not offered:
        return reject('state_answer_unknown')
    try:
        choices = response['choices']
        if len(choices) != 1 or choices[0]['finish_reason'] != 'stop':
            return reject('state_answer_unfinished')
        content = choices[0]['message']['content']
        if not isinstance(content, str) or len(content) > 1024:
            return reject('state_answer_invalid')
        value = json.loads(content, object_pairs_hook=lambda fields: fields)
    except (IndexError, KeyError, TypeError, ValueError):
        return reject('state_answer_invalid')
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], tuple):
        return reject('state_answer_invalid')
    field, refs = value[0]
    if (field != 'state_refs' or not isinstance(refs, list) or len(refs) > 4
            or any(not isinstance(ref, str) or ref not in offered for ref in refs)
            or len(set(refs)) != len(refs)):
        return reject('state_answer_invalid')
    if not refs:
        return {'status': 'state_answer_unknown', 'state_refs': [], 'answer': _UNKNOWN}
    return {'status': 'state_answer_published', 'state_refs': refs,
            'answer': '\n'.join(offered[ref] for ref in refs)}
