"""One explicit structured publication attempt; no retries or free-text fallback."""
import json


def answer(chat, service, binding_key, question, system, *, max_tokens=2048):
    # No core imports at module load: legacy frozen-core replay stays importable.
    from wsc.csm.cem.source_claims import SourceClaimSession
    session = SourceClaimSession(service, binding_key)
    context = json.dumps(session.context(), ensure_ascii=False, separators=(',', ':'))
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': 'Question: ' + question + '\nMemories: ' + context}]
    raw = chat.exchange(messages, tools=[session.definition()], tool_choice='auto', max_tokens=max_tokens)
    published = session.publish_response(raw)
    return {'answer': published['answer'], 'publication': published,
            'raw_response': raw, 'raw_response_scope': 'unpublished_model_output'}
