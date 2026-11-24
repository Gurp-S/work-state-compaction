"""Mechanical triggers for one distillation call.

A gated chain must not wait only for a new user instruction: failures and
recorded decisions in tool/assistant output also change what a later model
must know. Triggers stay deterministic and cheap; a cooldown bounds how often
a lingering high-signal state can call the model.
"""
from __future__ import annotations

import re

CONTINUE = re.compile(r'(?i)^continue\.?$')
FAILURE = re.compile(
    r'(?i)\b(?:error|exception|failed|failure|traceback|assertionerror|timeout)\b')
DECISION = re.compile(
    r'(?i)\b(?:decided|decision|instead|switch(?:ed|ing)? to|revert(?:ed)?|'
    r'root cause|because)\b')


def item_text(item: dict) -> str:
    if not isinstance(item, dict) or item.get('type') != 'message':
        return ''
    content = item.get('content')
    if isinstance(content, list):
        return ' '.join(str(part.get('text') or '') for part in content
                        if isinstance(part, dict))
    return str(content or '')


def instruction(delta: list) -> bool:
    """A user message that asks for something new; "Continue." does not count."""
    for item in delta:
        if item.get('type') != 'message' or item.get('role') != 'user':
            continue
        text = ' '.join((item_text(item) or '').split())
        if text and not CONTINUE.fullmatch(text):
            return True
    return False


def high_signal(delta: list) -> bool:
    """A failure result or an assistant-recorded decision, without a new user ask."""
    for item in delta:
        if item.get('type') == 'function_call_output':
            if FAILURE.search(str(item.get('output') or '')):
                return True
        elif item.get('type') == 'message' and item.get('role') == 'assistant':
            if DECISION.search(item_text(item)):
                return True
    return False


def needs_distillation(delta: list) -> bool:
    return instruction(delta) or high_signal(delta)


def should_distil(delta: list, *, round_number: int, last_signal: int = 0,
                  cooldown: int = 2) -> bool:
    """Round 1 and explicit instructions always run. A high-signal-only round
    runs at most once per ``cooldown`` rounds, counted from the last such round;
    a lingering failure therefore does not call the model every round."""
    if round_number <= 1 or instruction(delta):
        return True
    if not high_signal(delta):
        return False
    return round_number - last_signal >= cooldown
