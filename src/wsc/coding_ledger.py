"""Engine-owned literals: identifying tokens, exact values and value-copy dedupe.

This is the production home of the "engine carries facts, model carries
judgment" split. It performs no semantic choice: a tool result either contains
an exact-value signal or it does not, and every qualifying result gets a stable
key in event order. Presentation may keep only the newest rows but must name
the archived keys, so a value is never silently lost.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256

# A tool result that states an exact value is discovery surface of its own: the
# engine can list it without understanding which value the task will need.
VALUE_SIGNAL = re.compile(r'\b[A-Z]{2,}\d+\b|\b(?:is|=|:)\s*[-+]?\d+(?:\.\d+)?\b')

TERM_PATTERNS = (
    re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)'),
    re.compile(r'\b[A-Z]{2,}-\d+\b'),
    re.compile(r'\b[A-Z][A-Z0-9_]{2,}\b'),
    re.compile(r'\b[a-z]+[A-Z][A-Za-z0-9]+\b'),
    re.compile(r'\b[a-z][a-z0-9]*_[a-z0-9_]+\b'),
    re.compile(r'\b\d{2,}\b'),
    re.compile(r'(?i)\b(?:winerror|http|errno)\s*\d+'),
    re.compile(r'(?i)\b(?:node --test[^\n]{0,30}|python -m unittest[^\n]{0,40})'),
)

PURE_VALUE_RELATION = re.compile(
    r'^(?:[^:=]{1,80}:\s*)?[^=]{1,60}=\s*[A-Za-z0-9_./"\'\\-]+$')


def terms_of(text: str, limit: int = 6) -> list:
    """Mechanical identifying tokens: paths, identifiers, numbers, codes, commands."""
    found = []
    for pattern in TERM_PATTERNS:
        for match in pattern.findall(text or ''):
            value = match.strip()[:48]
            # Encoded payloads can bleed JSON punctuation into a match; a token
            # with quotes or braces is not a literal the entry should copy.
            if not value or any(char in value for char in '"\\{}[]'):
                continue
            if value.lower() not in {item.lower() for item in found}:
                found.append(value)
            if len(found) >= limit:
                return found
    return found


def event_command(event) -> str:
    if event is None:
        return ''
    payload = event.payload or {}
    if payload.get('name') not in ('pwsh', 'bash', 'shell'):
        return ''
    args = payload.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return ''
    return str((args or {}).get('command') or '')


def cargs_test(command: str) -> bool:
    return bool(re.search(r'(?i)test|unittest|pytest|check', command or ''))


def _arguments(event) -> dict:
    payload = (event.payload if event is not None else None) or {}
    args = payload.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return args if isinstance(args, dict) else {}


def _target(event) -> str:
    args = _arguments(event)
    return next((args.get(key) for key in ('path', 'file_path', 'target_file')
                 if isinstance(args.get(key), str) and args.get(key)), '')


def value_rows(events: list) -> list:
    """Every tool result that states an exact value, addressable by a stable key.

    Value rows are engine-owned and cost no model tokens. Keys follow event
    order, so a render that keeps only the newest rows can name the archived
    keys explicitly instead of dropping them silently.
    """
    calls = {event.call_id: event for event in events if event.kind == 'call'}
    rows, seen = [], set()
    for index, event in enumerate(events):
        text = (event.text or '').strip()
        if event.kind != 'result' or not text:
            continue
        if re.search(r'(?i)error|exception|permissionerror|failed|traceback', text):
            continue
        call = calls.get(event.call_id)
        if cargs_test(event_command(call)):
            continue
        if not VALUE_SIGNAL.search(text):
            continue
        digest = sha256(text.encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        target = _target(call)
        first = next((line.strip() for line in text.split('\n') if line.strip()), '')[:72]
        rows.append({'key': f'V{len(rows) + 1}', 'source_id': event.id, 'message': index + 1,
                     'label': (f'{target}: {first}' if target else first)[:96],
                     'terms': terms_of(text), 'text': text})
    return rows


def merge_engine_values(entries: list, values: list) -> list:
    """Hide ledger facts that only restate a value the engine already lists.

    Presentation only: the stored entries and the engine state are untouched,
    so a later round still sees what the model originally wrote.
    """
    if not values:
        return entries
    tokens = set()
    for row in values:
        tokens.update(term.lower() for term in row.get('terms', ()))
        tokens.update(term.lower() for term in terms_of(row.get('text', '')))
    shown = []
    for entry in entries:
        text = (entry.get('text') or '').strip()
        if (entry.get('kind') == 'fact' and PURE_VALUE_RELATION.match(text)
                and any(token.lower() in tokens
                        for token in re.findall(r'[A-Za-z0-9_]{3,}', text))):
            continue
        shown.append(entry)
    return shown
