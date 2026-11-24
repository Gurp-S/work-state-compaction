"""Opt-in request and response-envelope policy; no model-visible directives."""
import os


class TextEnvelopeError(RuntimeError):
    """A failed text envelope is not retried as a network exception."""


def selected_policy():
    value = os.environ.get('CSM_BENCH_TRANSPORT_POLICY', 'legacy').strip().lower()
    if value not in {'legacy', 'text-only', 'purpose-routed'}:
        raise ValueError('CSM_BENCH_TRANSPORT_POLICY must be legacy, text-only, or purpose-routed')
    return value


SEMANTIC_PURPOSES = frozenset({'answer', 'handoff', 'select', 'extract', 'resolve', 'judge'})


def configure(payload, policy, purpose='answer'):
    if policy == 'legacy':
        return payload
    if policy not in {'text-only', 'purpose-routed'}:
        raise ValueError('Unknown transport policy')
    if payload.get('tools'):
        raise ValueError('text-only policy does not accept tool definitions')
    if policy == 'purpose-routed':
        if purpose not in SEMANTIC_PURPOSES | {'format'}:
            raise ValueError('Unknown request purpose')
        if purpose in SEMANTIC_PURPOSES:
            return {**payload, 'thinking': {'type': 'enabled'},
                    'reasoning_effort': 'low', 'tool_choice': 'none'}
    configured = {**payload, 'thinking': {'type': 'disabled'}, 'tool_choice': 'none'}
    configured.pop('reasoning_effort', None)
    return configured


def validate_text_envelope(data, *, allow_reasoning=False):
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise TextEnvelopeError('Text response choices missing')
    choice = choices[0]
    if choice.get('finish_reason') != 'stop':
        raise TextEnvelopeError('Text response not complete: ' + str(choice.get('finish_reason')))
    message = choice.get('message')
    if not isinstance(message, dict):
        raise TextEnvelopeError('Text response message missing')
    if message.get('tool_calls') or message.get('function_call'):
        raise TextEnvelopeError('Text response contains unrequested tool calls')
    content = message.get('content')
    if not isinstance(content, str) or not content.strip():
        raise TextEnvelopeError('Text response content empty')
    usage = data.get('usage') or {}
    details = usage.get('completion_tokens_details') or {}
    if not allow_reasoning and (message.get('reasoning_content') or details.get('reasoning_tokens', 0)
                               or usage.get('completion_thinking_tokens', 0)):
        raise TextEnvelopeError('Text response contains reasoning despite disabled thinking')
    # `stop` is a transport field. It does not certify semantic completeness,
    # correctness, source support, or that an upstream intermediary kept all text.
    return content
