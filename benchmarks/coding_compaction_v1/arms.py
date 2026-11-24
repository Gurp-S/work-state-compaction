"""Reference compaction arms used to prove the fixtures can separate algorithms.

Three strategies over the same chunks and the same byte budget:

* ``truncation`` — keep the most recent messages (the classic baseline).
* ``extractive`` — keep the whole messages with the strongest keyword salience
  (paths, errors, code, constraints, decisions); a strong retrieval-free
  extractive baseline.
* ``wsc`` — the product pipeline: distilled ledger entries that persist across
  rounds, mechanically expired when their cited source changes, plus selected
  evidence.

A fixture set that cannot make these three score differently is not an eval
set; the runner checks the spread per case, per round.
"""
from __future__ import annotations

import hashlib
import json
import re

PATH = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)')
ERROR = re.compile(r'(?i)\b(error|exception|traceback|failed|panic|permissionerror)\b')
CODE = re.compile(r'(?m)^\s*(def |class |function |const |let |var |import |from |export function |ALLOWLIST )')
CONSTRAINT = re.compile(r'(?i)\b(must|must not|do not|never|required|不得|必须|禁止|保留|约束|requirement)\b')
DECISION = re.compile(r'(?i)\b(decided|chose|choose|will use|adopt|revised)\b')


def flatten(value) -> str:
    """Decode JSON-object strings (the working-state block, tool arguments).

    A checkpoint renders structured content as a JSON string. Comparing raw
    escapes would count `\\"` as content that no reader ever sees, so the
    material is compared in its decoded form for every arm.
    """
    parts = []

    def walk(node):
        if isinstance(node, str):
            text = node.strip()
            if text.startswith('{') and text.endswith('}'):
                try:
                    walk(json.loads(text))
                    return
                except ValueError:
                    pass
            parts.append(node)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return '\n'.join(parts)


def chunks_of(items: list) -> list:
    return [{'text': flatten(item), 'index': index} for index, item in enumerate(items)]


def truncation(chunks: list, budget: int) -> dict:
    """Most recent chunks first until the budget is spent."""
    kept, used = [], 0
    for chunk in reversed(chunks):
        cost = len(chunk['text'].encode()) + 1
        if used + cost > budget:
            continue
        used += cost
        kept.append(chunk)
    kept.reverse()
    return _material('truncation', kept, budget)


def _salience(text: str) -> int:
    return (3 * len(PATH.findall(text)) + 3 * len(ERROR.findall(text))
            + 2 * len(CODE.findall(text)) + 3 * len(CONSTRAINT.findall(text))
            + 2 * len(DECISION.findall(text)))


def extractive(chunks: list, budget: int) -> dict:
    """Whole chunks by salience density, then recency; budget-greedy."""
    scored = []
    for chunk in chunks:
        salience = _salience(chunk['text'])
        if salience == 0:
            continue
        scored.append((salience / max(1, len(chunk['text'].encode())), chunk['index'], chunk))
    scored.sort(reverse=True)
    kept, used, seen = [], 0, set()
    for _, _, chunk in scored:
        digest = hashlib.sha256(chunk['text'].encode()).hexdigest()
        if digest in seen:
            continue
        cost = len(chunk['text'].encode()) + 1
        if used + cost > budget:
            continue
        used += cost
        seen.add(digest)
        kept.append(chunk)
    kept.sort(key=lambda chunk: chunk['index'])
    return _material('extractive', kept, budget)


def _material(name: str, kept: list, budget: int) -> dict:
    text = '\n'.join(chunk['text'] for chunk in kept)
    return {'arm': name, 'text': text, 'bytes': len(text.encode()), 'budget': budget,
            'chunks': len(kept)}


def carry_text(previous: dict) -> list:
    """A baseline's next round starts from its own previous output as one blob."""
    return [{'text': previous['text'], 'index': -1}]
