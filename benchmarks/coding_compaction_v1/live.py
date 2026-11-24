"""Live two-arm comparison: DSH native compaction vs WSC, same model, same bytes.

Both arms compress the same fixture region with the same model
(``deepseek-flash`` on the OpenAI-compatible endpoint). The acts are the ones
each side actually ships:

* ``dsh_native`` replays the conversation and appends the exact compaction
  instruction shipped in ``@deepseek-ai/dsh-compaction-basic`` (extracted from
  the installed Harness). The summary replaces the oldest span and the newest
  messages stay verbatim.
* ``wsc`` asks the model only for meaning: ledger entries (H2 write-back) whose
  cites also select the evidence, one call per compression. WSC itself then
  builds the checkpoint deterministically, mechanically expires entries whose
  cited file changed, and exports verified evidence.
* ``wsc_lean`` is the same engine with a leaner model contract: round 2 and
  later receive only that round's new messages plus the current ledger, and the
  create/update rules are a single prompt.

Scoring is mechanical presence/absence of distinctive needles, so a paraphrase
that drops an exact path, error string or number is a miss for either arm.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]

from wsc import WSC, Store, Selection, Understanding, Limits, WSCError  # noqa: E402
from wsc.adapters.codex import CodexCheckpointAdapter  # noqa: E402
from wsc.coding_ledger import (VALUE_SIGNAL, TERM_PATTERNS, terms_of, event_command,  # noqa: E402
                               cargs_test, merge_engine_values,
                               value_rows as value_rows_from_events)
from wsc.state_view import current_entries, entry_expired, latest_observed_at  # noqa: E402
from wsc.passage import index_text, render as render_passage  # noqa: E402
from coding_compaction_v1 import arms, cases as case_module  # noqa: E402
from coding_compaction_v1 import cost as cost_module  # noqa: E402

API_URL = os.environ.get('WSC_API_URL', 'http://192.168.128.161:3000/v1/chat/completions')
MODEL = os.environ.get('WSC_MODEL', 'deepseek-flash')
KEY_FILE = Path(os.environ.get('WSC_KEY_FILE', Path.home().parent / 'Administrator' / 'Desktop' / 'new_api_key.txt'))
MAX_RATIO = 0.85
DEFAULT_BUDGET_FRACTION = 0.5

# Shipped in @deepseek-ai/dsh-compaction-basic (lib/index.js, COMPACTION_INSTRUCTION).
NATIVE_INSTRUCTION = "\n".join([
    'You are now acting as a compaction engine for this AI coding assistant. Condense the conversation ABOVE into a structured checkpoint that lets another model resume the work with no loss of essential context.',
    '',
    'Output EXACTLY the Markdown structure below: keep every section, in order. Use terse bullets, not prose paragraphs. Write "(none)" for an empty section — never drop a section.',
    '',
    '## Primary Request and Intent',
    "- [the user's original and evolving goals; quote verbatim where the exact wording matters]",
    '',
    '## Key Technical Concepts',
    '- [technologies, frameworks, patterns, and conventions in play]',
    '',
    '## Files and Code',
    '- [exact path: why it matters, key changes or snippets]',
    '',
    '## Errors and Fixes',
    '- [error: how it was resolved, plus any related user feedback]',
    '',
    '## Pending Jobs',
    '- [explicitly requested work not yet completed]',
    '',
    '## Current Work',
    '- [precisely what was in progress at this checkpoint]',
    '',
    '## Next Step',
    '- [the single next action, directly in line with the most recent request, or "(none)"]',
    '',
    '## Critical Context',
    '- [decisions and their rationale, constraints, user preferences, open questions, data needed to continue]',
    '',
    'Rules:',
    '- Write concise English engineering prose. Preserve exact file paths, commands, error strings, identifiers, numeric values, function signatures, and syntax fragments.',
    '- Capture user feedback and explicit instructions faithfully, especially corrections.',
    '- Do NOT mention this summarization request or that the context was compacted.',
    '- Output only the checkpoint text: do not call any tool or take any other action.',
    '- If the conversation already contains a <compacted-summary> block, it is a PRIOR checkpoint. Do not copy it forward verbatim: preserve still-true facts, drop stale ones, and merge newer information into a single consolidated summary under the same structure.',
])
CHECKPOINT_PREAMBLE = ('This is an automatically generated checkpoint condensing an earlier span of the '
                       'conversation to free up context. Treat the captured context as established '
                       'background and build on it without restating it. Continue the task directly from '
                       'the messages that follow, without acknowledging this checkpoint.')
NATIVE_RETAIN = 0.16

DISTILL = "\n".join([
    'The transcript above is a numbered coding session: each message is labelled [m<number> <role>].',
    'Write the durable work ledger a later model needs to continue the work. Return only a JSON object:',
    '{"entries":[{"kind":"constraint|requirement|decision|verification|fact","text":"<one line>","cites":[<message numbers>],"invalid_when":{"file_changed":"<exact path>"}}]}',
    'Rules:',
    '- At most 8 entries. One claim per entry, one line, at most 180 characters; keep exact identifiers, numbers, paths and error strings verbatim.',
    '- kind: constraint/requirement for user rules, decision for a chosen approach and its reason, verification for a result bound to a version, fact otherwise.',
    '- Never record process narration: not "tool returned ok", "edit applied", "receipt reissued", not that a command ran, and not a file summary. Record the claim it changes.',
    '- A verification must name what it covers ("after edit m10", "before edit m10", or the version id). An unqualified "tests passed" is not a verification: omit it; the engine records the gap from the tool events.',
    '- cites must name the message numbers that support the entry; omit an entry you cannot cite.',
    '- invalid_when is allowed only for an exact path whose later edit in this transcript makes the entry false; otherwise omit the field.',
    '- Do not invent. Omit rather than guess. Output only the JSON object.',
])

REVISE = "\n".join([
    'The transcript above is the continuing coding session. The current ledger is listed after it.',
    'Update the ledger. Return only a JSON object:',
    '{"entries":[{"kind":"constraint|requirement|decision|verification|fact","text":"<one line>","cites":[<message numbers>],"invalid_when":{"file_changed":"<exact path>"}}],'
    '"revise":[{"ref":"<current ref>","text":"<new line>","cites":[<message numbers>]}],'
    '"supersede":["<current ref>"]}',
    'Rules:',
    '- entries are new facts not already in the ledger; revise replaces a current entry in place; supersede marks a current entry no longer true.',
    '- At most 8 entries and 8 revisions. One claim per line, at most 180 characters; keep exact identifiers, numbers, paths and error strings verbatim.',
    '- When a new message changes or narrows an earlier entry, you MUST revise it (or supersede it and state the replacement). Never leave the old and the new current at once.',
    '- Replacement check: a user message that says "Change:", "changed", "now", "instead", "no longer" or "replace" about the same file or subject replaces the earlier requirement. Supersede the old requirement entry in this same output; two active contradicting requirements is an error.',
    '- An edit to a file makes an earlier verification of that file stale. If the new messages contain a check after the edit, add a version-qualified verification citing both messages; if they do not, do not restate the old result; the engine records the gap.',
    '- Never record process narration ("tool returned ok", "edit applied", "receipt reissued", a command ran).',
    '- cites the supporting message numbers. Output only the JSON object.',
])


# One rule set for both the first compression and later ones: the create and
# update instructions are merged, and only the new round's messages are sent.
LEAN = "\n".join([
    'The transcript above is a numbered coding session: each message is labelled [m<number> <role>].',
    'Write and update the durable work ledger a later model needs to continue the work. Return only a JSON object:',
    '{"entries":[{"kind":"constraint|requirement|decision|verification|fact","text":"<one line>","cites":[<message numbers>],"invalid_when":{"file_changed":"<exact path>"}}],'
    '"revise":[{"ref":"<current ref>","text":"<new line>","cites":[<message numbers>]}],'
    '"supersede":["<current ref>"]}',
    'Rules:',
    '- entries are new claims from this transcript; revise replaces a current ledger entry in place; supersede marks one no longer true. Omit revise and supersede when the current ledger is empty or nothing changed.',
    '- At most 8 entries and 8 revisions. One claim per line, at most 180 characters; keep exact identifiers, numbers, paths and error strings verbatim.',
    '- kind: constraint/requirement for user rules, decision for a chosen approach and its reason, verification for a result bound to a version, fact otherwise.',
    '- When a message changes or narrows an earlier entry, you MUST revise it (or supersede it and state the replacement). Never leave the old and the new current at once.',
    '- Replacement check: a user message that says "Change:", "changed", "now", "instead", "no longer" or "replace" about the same file or subject replaces the earlier requirement. Supersede the old requirement entry in this same output; two active contradicting requirements is an error.',
    '- An edit to a file makes an earlier verification of that file stale. If a later message records a check, add a version-qualified verification; if not, do not restate the old result; the engine records the gap.',
    '- Never record process narration: not "tool returned ok", "edit applied", "receipt reissued", that a command ran, or a file summary.',
    '- cites are the [m<number>] labels above; omit an entry you cannot cite. Do not invent. Output only the JSON object.',
])


# Relation-only contract: the ledger carries values and bindings, not prose.
# It is an arm of its own so output-cost changes stay comparable with wsc/lean.
REL = "\n".join([
    'The transcript above is a numbered coding session: each message is labelled [m<number> <role>].',
    'Write the durable ledger as relations only. Return only a JSON object:',
    '{"entries":[{"kind":"constraint|requirement|decision|verification|fact","text":"<one relation>","cites":[<message numbers>]}],'
    '"revise":[{"ref":"<current ref>","text":"<one relation>","cites":[<message numbers>]}],'
    '"supersede":["<current ref>"]}',
    'Rules:',
    '- At most 5 entries and 4 revisions per round. One relation per entry, at most 100 characters.',
    '- Use these shapes: "<path>: <symbol> = <exact value>", "<path>: <property> is <exact value>",'
    ' "after edit #<n>: <exact result>", "decision: <choice> (<reason in a few words>)".',
    '- Never restate a user requirement; the engine quotes user messages verbatim.',
    '- Never describe an edit or a command that ran; the engine derives edits, checks and versions from events.',
    '- Keep exact identifiers, numbers, paths and error strings verbatim.',
    '- When a message changes an earlier relation, revise it; never keep both current.',
    '- cites are the [m<number>] labels above; omit an entry you cannot cite. Do not invent.',
    'Output only the JSON object.',
])


# Extraction-only contract: the model copies relations out of the delta; it is
# not asked to judge the ledger, so a round costs roughly half the reasoning of
# REL and the engine carries the exact values through its index.
EXT = "\n".join([
    'The transcript above is a numbered coding-session region: each message is labelled [m<number> <role>].',
    'Extract the durable relations a later model cannot recompute from the events. Return only a JSON object:',
    '{"entries":[{"kind":"decision|fact","text":"<one relation>","cites":[<message numbers>]}],'
    '"revise":[{"ref":"<current ref>","text":"<new relation>","cites":[<message numbers>]}]}',
    'Rules:',
    '- Copy exact values from tool results; never paraphrase a value, path, identifier or number.',
    '- Use these shapes: "<path or source>: <name> = <exact value>", "<property> is <exact value>",'
    ' "decision: <choice> (<reason in a few words>)".',
    '- Do not restate user messages; the engine quotes them verbatim. Do not describe commands or edits; the engine derives them.',
    '- At most 5 entries and 3 revisions. One relation each, at most 100 characters.',
    '- revise only a current relation this round contradicts or narrows; quote its ref. Never keep both current.',
    '- cites are the [m<number>] labels above; omit an entry you cannot cite. Omit rather than guess.',
    'Output only the JSON object.',
])


# Diagnostic arm only: extraction without the revision decision. A later round
# that contradicts an earlier relation is left unrepaired, so this contract
# must not enter the default path.
EXT_NOREV = "\n".join([
    'The transcript above is a numbered coding-session region: each message is labelled [m<number> <role>].',
    'Extract the durable relations a later model cannot recompute from the events. Return only a JSON object:',
    '{"entries":[{"kind":"decision|fact","text":"<one relation>","cites":[<message numbers>]}]}',
    'Rules:',
    '- Copy exact values from tool results; never paraphrase a value, path, identifier or number.',
    '- Use these shapes: "<path or source>: <name> = <exact value>", "<property> is <exact value>",'
    ' "decision: <choice> (<reason in a few words>)".',
    '- Do not restate user messages; the engine quotes them verbatim. Do not describe commands or edits; the engine derives them.',
    '- At most 5 entries. One relation each, at most 100 characters.',
    '- Do not compare with, revise or invalidate any earlier relation; extract only what this region states.',
    '- cites are the [m<number>] labels above; omit an entry you cannot cite. Omit rather than guess.',
    'Output only the JSON object.',
])


# Extraction-only contract for the cost arm: the engine already lists exact
# values, so the model records only what the engine cannot derive.
EXT2 = "\n".join([
    'The transcript above is a numbered coding-session region: each message is labelled [m<number> <role>].',
    'Record only what the engine cannot derive. Return only a JSON object:',
    '{"entries":[{"kind":"decision|requirement|fact","text":"<one relation>","cites":[<message numbers>]}],'
    '"revise":[{"ref":"<current ref>","text":"<new relation>","cites":[<message numbers>]}]}',
    'Rules:',
    '- Do not copy tool-result values or command output; the engine lists them verbatim. Never restate user messages; the engine quotes them.',
    '- A decision must keep the exact identifier it chooses and the exact path it applies to; those are not in the engine labels.',
    '- Record only a decision and its reason, a value role not visible in the engine label, or a correction the engine cannot see.',
    '- One relation per entry, at most 100 characters. At most 3 entries and 1 revision.',
    '- revise only when this round\'s user text explicitly reverses a current relation.',
    '- cites are the [m<number>] labels above; omit an entry you cannot cite. Omit rather than guess.',
    'Output only the JSON object.',
])


# Thin state-control layer: the model fills bounded slots; the engine owns
# ordering, expiry, verification receipts, control text and evidence bytes.
THIN_RULES = [
    'You maintain a durable work state for a long coding session. The transcript above is numbered [m<number> <role>]; each body line is numbered `N| ` (that prefix is not part of the text).',
    'Return only a JSON object of this exact shape:',
    '{"entries":[{"kind":"constraint|requirement|decision|verification|fact","text":"<one line>","invalid_when":{"file_changed":"<exact path>"}}],'
    '"replaces":[{"ref":"<current ref>","kind":"constraint|requirement|decision|verification|fact","text":"<one line>","invalid_when":{"file_changed":"<exact path>"}}],'
    '"state":{"done":[],"open":[],"next":[],"unknown":[]}}',
    'Rules:',
    '- At most 8 entries. One claim per entry, one line, at most 180 characters; keep exact identifiers, numbers, paths and error strings verbatim.',
    '- Quote the transcript\'s own wording for a value, result or version. Never paraphrase a qualifier: "stateCap lowered to 800 bytes" must not become "stateCap is 800 bytes".',
    '- The engine copies user messages verbatim into a Control block. Never write a constraint or requirement entry for text a user message already states; entries carry interpretation, decisions, verification and judgments.',
    '- If a message after an edit records a check or its outcome, keep its exact result wording and write a version-bound verification. Do not report it as a gap.',
    '- Never record process narration: not "tool returned ok", "edit applied", "receipt reissued", that a command ran, or a file summary.',
    '- A verification must name what it covers: the file and that it follows the edit ("after the edit to src/x.py"), the version id, or "before the edit". An unqualified "tests passed" is not a verification; omit it and state the gap.',
    '- replaces: when a later message changes or narrows an earlier entry, write the new text here under that ref. Never leave the old and the new current. Omit replaces when nothing changes.',
    '- invalid_when: set only when a later edit to that exact path makes the entry false; otherwise omit the field.',
    '- state: done = completed and verified, open = unfinished, next = the single recorded next action, unknown = what the transcript does not establish (for example "no post-edit verification for <path>"). A nonempty open requires next; if no next is recorded, move the gap to unknown. Never restate a stale claim in unknown; name only what evidence is missing.',
    '- Do not repeat in state any sentence already in the ledger. State records work status and the next action, not a second copy of conclusions.',
    '- Keep each entry to its one claim in one clause; do not add restatements, hedges or summaries of other entries.',
    '- Do not output message numbers, source pointers or quoted blocks. The engine archives every source itself and exposes a short evidence index; record only the judgment that must survive.',
    '- Omit rather than guess. Output only the JSON object.',
]
THIN_CREATE = '\n'.join(THIN_RULES)
THIN_UPDATE = '\n'.join(THIN_RULES + [
    '',
    'Update rules:',
    '- Apply replaces or an invalidating entry for anything the new messages change; a claim the new messages narrow must not remain current unchanged.',
    '- If an edit invalidates an earlier verification and the new messages contain no check after it, do not write a verification; put "no post-edit verification for <path>" in unknown.',
    '- Keep the state current: move finished open items to done and update next. Do not re-list unchanged items with new wording.',
])


class Model:
    """One endpoint, one model, retries; responses are cached for the matched pass."""

    def __init__(self, key: str, name: str | None = None):
        self.key = key
        self.name = name or MODEL
        self.calls = []
        self.responses = []
        self.cache = {}
        self.lock = threading.Lock()

    def chat(self, messages: list, max_tokens: int = 4096, label: str = '') -> dict:
        # The arm label is part of the key: two arms may send identical requests,
        # and a shared cache entry would hide one arm's cost from its own tally.
        key = hashlib.sha256(json.dumps([self.name, label, messages, max_tokens],
                                        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key in self.cache:
                return {**self.cache[key], 'cached': True}
        payload = json.dumps({'model': self.name, 'messages': messages,
                              'max_tokens': max_tokens, 'temperature': 0}).encode()
        last = None
        for attempt in range(5):
            started = time.time()
            try:
                request = urllib.request.Request(API_URL, data=payload, headers={
                    'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
                with urllib.request.urlopen(request, timeout=600) as response:
                    body = json.loads(response.read())
                message = (body.get('choices') or [{}])[0].get('message') or {}
                result = {'text': message.get('content') or '',
                          'finish': (body.get('choices') or [{}])[0].get('finish_reason'),
                          'usage': body.get('usage') or {}, 'elapsed': round(time.time() - started, 3),
                          'cached': False}
                with self.lock:
                    self.cache[key] = result
                    self.calls.append({'label': label, 'usage': result['usage'],
                                       'finish': result['finish'], 'elapsed': result['elapsed'],
                                       'chars': len(result['text']),
                                       'request_chars': len(json.dumps(messages))})
                    self.responses.append({'label': label, 'finish': result['finish'],
                                           'text': result['text']})
                return result
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                time.sleep((10 if error.code == 429 else 2) * (attempt + 1))
            except (urllib.error.URLError, TimeoutError) as error:
                last = error
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f'model_call_failed: {last}')

    def totals(self) -> dict:
        return {'calls': len(self.calls),
                'prompt_tokens': sum(c['usage'].get('prompt_tokens', 0) for c in self.calls),
                'completion_tokens': sum(c['usage'].get('completion_tokens', 0) for c in self.calls),
                'elapsed': round(sum(c['elapsed'] for c in self.calls), 2)}


def load_key() -> str:
    import os
    key = os.environ.get('DEEPSEEK_API_KEY')
    if key:
        return key.strip()
    return KEY_FILE.read_text(encoding='utf-8').strip()


def item_text(item: dict) -> str:
    kind = item.get('type')
    if kind == 'message':
        return '\n'.join(part['text'] for part in item.get('content', [])
                         if isinstance(part, dict) and isinstance(part.get('text'), str))
    if kind in ('function_call', 'custom_tool_call'):
        return f"CALL {item.get('name')} {item.get('arguments') or item.get('input') or ''}"
    if kind in ('function_call_output', 'custom_tool_call_output'):
        output = item.get('output')
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return ''


def numbered(items: list, line_numbers: bool = True) -> str:
    parts = []
    for index, item in enumerate(items, 1):
        role = item.get('role') if item.get('type') == 'message' else (
            'tool-result' if str(item.get('type', '')).endswith('_output') else 'tool-call')
        body = item_text(item)
        if line_numbers:
            body = '\n'.join(f'{n}| {line}' for n, line in enumerate(body.split('\n'), 1))
        parts.append(f'[m{index} {role}]\n{body}')
    return '\n\n'.join(parts)


def transcript_messages(items: list) -> list:
    """Native replay: real roles, no addressing labels."""
    result = []
    for item in items:
        body = item_text(item)
        if not body:
            continue
        if item.get('type') == 'message':
            result.append({'role': 'assistant' if item.get('role') == 'assistant' else 'user',
                           'content': body})
        elif str(item.get('type', '')).endswith('_output'):
            result.append({'role': 'user', 'content': 'Tool result:\n' + body})
        else:
            result.append({'role': 'assistant', 'content': 'Tool call:\n' + body})
    return result


def json_object(text: str):
    body = (text or '').strip()
    fence = re.match(r'^```(?:json)?\s*([\s\S]*?)\s*```$', body)
    if fence:
        body = fence.group(1).strip()
    try:
        return json.loads(body)
    except ValueError:
        pass
    start, depth = None, 0
    for index, char in enumerate(body):
        if char == '{':
            if depth == 0:
                start = index
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(body[start:index + 1])
                except ValueError:
                    start = None
    return None


def fact_map(case: dict) -> dict:
    """Distinctive needle per oracle fact; ledger facts fall back to their text."""
    facts = {}
    for oracle in (case['oracle'], case['round2']['oracle']):
        for fact in oracle['evidence'] + oracle['ledger']:
            facts[fact['id']] = fact.get('needle') or fact['text']
    return facts


def claims_text(presented: str) -> str:
    """The passage minus the cold-store index: what the checkpoint asserts as current."""
    marker = '\n\nEvidence index (fetch by key)'
    return presented.split(marker)[0]


def score(case: dict, round_number: int, presented: str, current: str | None = None) -> dict:
    facts = fact_map(case)
    oracle = case['oracle'] if round_number == 1 else case['round2']['oracle']
    probes = case['probes'] if round_number == 1 else case['round2']['probes']
    retained = {f['id']: facts[f['id']] in presented for f in oracle['evidence'] + oracle['ledger']}
    constraints = [f for f in oracle['ledger'] if f['kind'] == 'constraint']
    probe_hits = probe_total = 0
    failures, stale = [], []
    for probe in probes:
        for fact_id in probe['expects']:
            probe_total += 1
            if facts[fact_id] in presented:
                probe_hits += 1
            else:
                failures.append({'probe': probe['question'], 'missing': fact_id})
        for fact_id in probe.get('excludes', []):
            probe_total += 1
            if facts[fact_id] not in (current if current is not None else presented):
                probe_hits += 1
            else:
                stale.append(fact_id)
    return {
        'key_recall': round(sum(retained.values()) / len(retained), 4) if retained else None,
        'constraint_retention': (round(sum(retained[f['id']] for f in constraints) / len(constraints), 4)
                                 if constraints else None),
        'probe': round(probe_hits / probe_total, 4) if probe_total else None,
        'stale': stale, 'missing': [key for key, ok in retained.items() if not ok],
        'probe_failures': failures,
    }


def needle_tokens(text: str) -> list:
    """Case carrying meaning counts double: ALLOWLIST is a stronger term than 'allowlist'."""
    return [(token, 2 if token.isupper() else 1)
            for token in re.findall(r'[A-Za-z0-9_]{3,}', text or '')]


def pick_index(index: list, needle: str):
    """Mechanical top-1: weighted token overlap with gist and terms; no model involved."""
    tokens = set(needle_tokens(needle))
    best = None
    for row in index:
        terms = ' '.join(row.get('terms', []))
        hay = (row['label'] + ' ' + terms).lower()
        score = 0
        for token, weight in tokens:
            if token.lower() in hay:
                score += weight
            if token != token.lower() and token in terms:
                score += weight
        if best is None or (score, -row['rank']) > (best[0], -best[1]['rank']):
            best = (score, row)
    return best


def evidence_scores(case: dict, round_number: int, index: list, archive_text: str) -> dict:
    """Discover@1 is whether the index leads to the right source; retrieve is cold bytes."""
    oracle = case['oracle'] if round_number == 1 else case['round2']['oracle']
    needles = [fact.get('needle') or fact['text'] for fact in oracle['evidence']]
    hits = 0
    for needle in needles:
        best = pick_index(index, needle)
        if best is not None and best[0] > 0 and needle in best[1]['text']:
            hits += 1
    return {'items': len(needles),
            'discover': round(hits / len(needles), 4),
            'retrieve': round(sum(needle in archive_text for needle in needles) / len(needles), 4)}


def archive_text(locators: dict) -> str:
    parts = []
    for locator in locators.values():
        try:
            parts.append(Path(locator['file_path']).read_text(encoding='utf-8', errors='ignore'))
        except OSError:
            continue
    return '\n'.join(parts)


def latest_region(*groups: list) -> str:
    return '\n'.join(arms.flatten(item) for item in [item for group in groups for item in group])


def run_native(model: Model, items: list, prior: str | None, budget: int, *, label: str) -> dict:
    replay = transcript_messages(items)
    if prior is not None:
        replay = [{'role': 'user', 'content': prior}] + replay
    total_bytes = sum(len(message['content'].encode()) for message in replay)
    keep, tail_bytes = [], 0
    for message in reversed(replay):
        cost = len(message['content'].encode())
        if tail_bytes + cost > NATIVE_RETAIN * total_bytes:
            break
        keep.append(message)
        tail_bytes += cost
    keep.reverse()
    cut = len(replay) - len(keep)
    head = replay[:cut]
    # Same request budget as WSC compression: configuration is not a hidden
    # variable in the arm comparison.
    output = model.chat(head + [{'role': 'user', 'content': NATIVE_INSTRUCTION}],
                        max_tokens=16384, label=label)
    text = CHECKPOINT_PREAMBLE + '\n<compacted-summary>\n' + output['text'].strip() + '\n</compacted-summary>'
    tail = '\n\n'.join(f"[m{i + 1} {m['role']}]\n{m['content']}" for i, m in enumerate(keep))
    presented = text + ('\n\n' + tail if tail else '')
    return {'presented': presented, 'summary': text, 'bytes': len(presented.encode()),
            'tail_bytes': len(tail.encode()), 'usage': output['usage']}


def distil(model: Model, item_list: list, entries: list, round_number: int, label: str) -> dict:
    if round_number == 1:
        prompt = DISTILL
        body = numbered(item_list)
    else:
        ledger = '\n'.join(f"- [{e['ref']}] {e['kind']}: {e['text']}" for e in entries) or '- (empty)'
        prompt = REVISE + '\n\nCurrent ledger:\n' + ledger
        body = numbered(item_list)
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return {'value': parsed if isinstance(parsed, dict) else {}, 'raw': output['text']}


def distil_rel(model: Model, item_list: list, entries: list, round_number: int, label: str) -> dict:
    """Full transcript per round with the relation-only contract."""
    body = numbered(item_list)
    prompt = REL
    if round_number > 1 and entries:
        ledger = '\n'.join(f"- [{e['ref']}] {e['kind']}: {e['text']}" for e in entries)
        prompt = REL + '\n\nCurrent ledger:\n' + ledger
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return {'value': parsed if isinstance(parsed, dict) else {}, 'raw': output['text']}


def distil_ext(model: Model, item_list: list, entries: list, round_number: int, label: str,
               hint: str = '', contract: str | None = None) -> dict:
    """Delta plus an extraction-only contract: no ledger analysis, no narration."""
    body = numbered(item_list)
    prompt = (contract or EXT) + (('\n\n' + hint) if hint else '')
    if round_number > 1 and entries:
        ledger = '\n'.join(f"- [{e['ref']}] {e['kind']}: {e['text']}" for e in entries)
        prompt = prompt + '\n\nCurrent relations:\n' + ledger
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return {'value': parsed if isinstance(parsed, dict) else {}, 'raw': output['text']}


def distil_ext2(model: Model, item_list: list, entries: list, round_number: int, label: str,
                hint: str = '') -> dict:
    """Delta plus the no-copy contract: values stay in the engine ledger."""
    body = numbered(item_list)
    prompt = EXT2 + (('\n\n' + hint) if hint else '')
    if round_number > 1 and entries:
        ledger = '\n'.join(f"- [{e['ref']}] {e['kind']}: {e['text']}" for e in entries)
        prompt = prompt + '\n\nCurrent relations:\n' + ledger
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return {'value': parsed if isinstance(parsed, dict) else {}, 'raw': output['text']}


def distil_lean(model: Model, item_list: list, entries: list, round_number: int, label: str) -> dict:
    """One merged prompt, and only this round's messages are sent after the first."""
    body = numbered(item_list)
    prompt = LEAN
    if round_number > 1 and entries:
        ledger = '\n'.join(f"- [{e['ref']}] {e['kind']}: {e['text']}" for e in entries)
        prompt = LEAN + '\n\nCurrent ledger:\n' + ledger
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return {'value': parsed if isinstance(parsed, dict) else {}, 'raw': output['text']}


def cited_indices(entries: list, items: list, ids: list, control=()) -> list:
    """Message indices the ledger cites, most load-bearing first.

    ``cites`` already names what supports each claim, so the evidence selection
    is derived instead of asked for a second time. A cited call drags its result
    along (and vice versa) or a later protocol read is ambiguous. Low-value
    sources sit at the tail, where ``fit`` trims first.
    """
    rank = {}
    lookup = {source: index for index, source in enumerate(ids)}
    for entry in entries:
        for source in entry.sources:
            index = lookup.get(source)
            if index is not None:
                rank[index] = max(rank.get(index, 0), RANK.get(entry.kind, 0))
    by_call = {}
    for index, item in enumerate(items):
        if item.get('call_id'):
            by_call.setdefault(item['call_id'], set()).add(index)
    for indices in by_call.values():
        if rank.keys() & indices:
            value = max(rank[index] for index in indices if index in rank)
            for index in indices:
                rank[index] = max(rank.get(index, 0), value)
    for index in control:
        rank[index] = max(rank.get(index, 0), max(RANK.values()) + 1)
    return sorted(rank, key=lambda index: (-rank[index], index))


def entry_from(raw: dict, items: list, ids: list, *, entry_id: str, revision=None,
               status: str = 'active', text=None) -> Understanding | None:
    text = (text if text is not None else raw.get('text', '')).strip()
    kind = str(raw.get('kind') or 'fact')
    cites = [n for n in raw.get('cites', []) or [] if isinstance(n, int) and 1 <= n <= len(items)]
    sources = tuple(ids[n - 1] for n in dict.fromkeys(cites))
    if not text or not sources:
        return None
    invalid = raw.get('invalid_when')
    return Understanding(text=text, kind=kind, sources=sources, id=entry_id,
                         expected_revision=revision, status=status,
                         invalid_when=invalid if isinstance(invalid, dict) else None)


def observed_at(start: int, count: int) -> list:
    return [f'2026-11-17T{(start + index) // 60:02d}:{(start + index) % 60:02d}:00Z'
            for index in range(count)]


def build_entries(distilled: dict, items: list, ids: list, *, prefix: str) -> list:
    entries = []
    for index, raw in enumerate(distilled.get('entries', [])[:12]):
        entry = entry_from(raw, items, ids, entry_id=f'{prefix}{index + 1}')
        if entry is not None:
            entries.append(entry)
    return entries


def build_revisions(distilled: dict, items: list, ids: list, entries1: list, tag: str) -> list:
    revisions = {}
    for index, raw in enumerate(distilled.get('entries', [])[:12]):
        entry = entry_from(raw, items, ids, entry_id=f'live-{tag}-r2-{index + 1}')
        if entry is not None:
            revisions[entry.id] = entry
    for item in distilled.get('revise', [])[:12]:
        match = re.match(r'(.+)@(\d+)$', str(item.get('ref', '')))
        if not match:
            continue
        entry = entry_from(item, items, ids, entry_id=match.group(1),
                           revision=int(match.group(2)))
        if entry is not None:
            revisions[entry.id] = entry
    for ref in (distilled.get('supersede', []) or [])[:12]:
        match = re.match(r'(.+)@(\d+)$', str(ref))
        if not match:
            continue
        original = next((entry for entry in entries1 if entry.id == match.group(1)), None)
        if original is None:
            continue
        revisions[original.id] = Understanding(
            text=original.text, kind=original.kind, sources=original.sources,
            invalid_when=original.invalid_when, id=original.id,
            expected_revision=int(match.group(2)), status='invalidated')
    return list(revisions.values())


def event_setup(case: dict) -> tuple:
    adapter = CodexCheckpointAdapter()
    items1, items2 = case['items'], case['round2']['items']
    events1 = adapter.import_items(items1, thread_id=case['case'],
                                   observed_at=observed_at(0, len(items1)))
    events2 = adapter.import_items(items2, thread_id=case['case'], start_ordinal=len(items1),
                                   observed_at=observed_at(len(items1), len(items2)))
    return adapter, items1, items2, events1, events2


def control_indices(items: list) -> list:
    return [index for index, item in enumerate(items)
            if item.get('type') == 'message' and item.get('role') == 'user']


def plan_of(chosen: list) -> dict:
    return {'whole': chosen, 'excerpts': [], 'spans': []}


def wsc_model_work(model: Model, case: dict, pool: ThreadPoolExecutor) -> dict:
    """One model call per compression.

    The ledger's ``cites`` also select the evidence, so no second call is made;
    ledger rows come from the distilled entries, not from what a given budget
    kept, so the matched-bytes pass replays these exact requests from cache.
    """
    adapter, items1, items2, events1, events2 = event_setup(case)
    ids1 = [event.id for event in events1]
    ids_all = ids1 + [event.id for event in events2]
    items_all = items1 + items2
    tag = case['case']
    distilled1 = pool.submit(distil, model, items1, [], 1, f'{tag}:wsc-distill-r1').result()['value']
    entries1 = build_entries(distilled1, items1, ids1, prefix=f'live-{tag}-d')
    rows = [{'ref': f'{entry.id}@1', 'kind': entry.kind, 'text': entry.text} for entry in entries1]
    distilled2 = pool.submit(distil, model, items_all, rows, 2, f'{tag}:wsc-distill-r2').result()['value']
    revisions = build_revisions(distilled2, items_all, ids_all, entries1, tag)
    chosen1 = cited_indices(entries1, items1, ids1, control_indices(items1))
    chosen2 = cited_indices(revisions, items_all, ids_all, control_indices(items_all))
    return {'events1': events1, 'events2': events2, 'ids1': ids1, 'ids_all': ids_all,
            'entries1': entries1, 'revisions': revisions,
            'plan1': plan_of(chosen1), 'plan2': plan_of(chosen2),
            'chosen1': chosen1, 'chosen2': chosen2,
            'distilled': distilled1, 'distilled2': distilled2}


def wsc_lean_model_work(model: Model, case: dict, pool: ThreadPoolExecutor) -> dict:
    """Same engine and one call per compression, with a leaner model contract.

    Round 2 and later send only that round's messages plus the current ledger,
    and the create/update rules are merged into one prompt.
    """
    adapter, items1, items2, events1, events2 = event_setup(case)
    ids1 = [event.id for event in events1]
    ids2 = [event.id for event in events2]
    ids_all = ids1 + ids2
    items_all = items1 + items2
    tag = case['case']
    distilled1 = pool.submit(distil_lean, model, items1, [], 1,
                             f'{tag}:lean-distill-r1').result()['value']
    entries1 = build_entries(distilled1, items1, ids1, prefix=f'live-{tag}-lean-d')
    rows = [{'ref': f'{entry.id}@1', 'kind': entry.kind, 'text': entry.text} for entry in entries1]
    distilled2 = pool.submit(distil_lean, model, items2, rows, 2,
                             f'{tag}:lean-distill-r2').result()['value']
    revisions = build_revisions(distilled2, items2, ids2, entries1, f'{tag}-lean')
    chosen1 = cited_indices(entries1, items1, ids1, control_indices(items1))
    chosen2 = cited_indices(revisions, items_all, ids_all, control_indices(items_all))
    return {'events1': events1, 'events2': events2, 'ids1': ids1, 'ids_all': ids_all,
            'entries1': entries1, 'revisions': revisions,
            'plan1': plan_of(chosen1), 'plan2': plan_of(chosen2),
            'chosen1': chosen1, 'chosen2': chosen2,
            'distilled': distilled1, 'distilled2': distilled2}


_PRESENT_RUNS = itertools.count(1)


def ledger_view(core: WSC) -> list:
    prefix, records = core.snapshot_content(core.capture())
    return [{'id': record['id'], 'kind': record['kind'], 'text': record['text'],
             'status': 'active', 'seq': 0, 'sources': tuple(record.get('sources') or ())}
            for record in current_entries(records, prefix)]


def present(case: dict, root: Path, budget: int, *, tag: str, work: dict) -> dict:
    """Deterministic assembly for one budget; no model calls.

    A budget rejection must not leave a half-written ledger, and ``prepare``
    writes as it validates. Each fit attempt therefore runs in its own scratch
    store; only the accepted attempt is staged.
    """
    adapter = CodexCheckpointAdapter()
    attempts = {'n': 0}
    run = next(_PRESENT_RUNS)

    def make_core(events):
        attempts['n'] += 1
        core = WSC(Store(root / f'{tag}-{run}-a{attempts["n"]}.db', session_id=case['case'],
                         workspace=str(root)), access=lambda *args: True)
        ids = core.ingest(events)
        return core, ids

    def r1_core(events):
        core, ids = make_core(events)
        core.presented('round-1', tuple(ids), receiver='live-model')
        return core, ids

    def r2_core(events):
        core, ids = make_core(events)
        core.presented('round-1', tuple(ids[:len(work['events1'])]), receiver='live-model')
        core.presented('round-2', tuple(ids[len(work['events1']):]), receiver='live-model')
        return core, ids

    plan1 = work['plan1']
    core1, ids1 = r1_core(work['events1'])
    sources1 = [ids1[index] for index in plan1['whole']]
    core1, view1, kept1 = fit(r1_core, work['events1'], sources1, list(plan1['excerpts']),
                              [], list(work['entries1']), budget)
    operation1 = core1.stage(view1, directory=root / f'{tag}-r1', adapter=adapter)
    # The measured package is never submitted; releasing the slot keeps round 2
    # a fresh compression rather than a replay of a pending install.
    core1.discard(operation1)
    control1 = [event.text for event in work['events1']
                if event.kind == 'message' and event.role == 'user' and (event.text or '').strip()]
    ledger1 = ledger_view(core1)
    receipts1 = receipts_from_events(work['events1'])
    state1 = engine_state(ledger1, work['events1'], receipts1)
    index1 = index_from_events(work['events1'])
    text1 = passage_text(control1, ledger1, state1, receipts1, list(index1), budget,
                         dropped=archived_without_slot(work['events1'], index1))

    plan2 = work['plan2']
    events_all = work['events1'] + work['events2']
    _, ids_all = r2_core(events_all)
    sources2 = [ids_all[index] for index in plan2['whole']]
    stored = {entry.id for entry in kept1}
    revisions = [value if value.expected_revision is None or value.id in stored
                 else replace(value, expected_revision=None)
                 for value in work['revisions']]
    core2, view2, kept2 = fit(r2_core, events_all, sources2, list(plan2['excerpts']),
                              kept1, revisions, budget)
    package2 = core2.package(core2.stage(view2, directory=root / f'{tag}-r2', adapter=adapter))
    control2 = [event.text for event in events_all
                if event.kind == 'message' and event.role == 'user' and (event.text or '').strip()]
    ledger2 = ledger_view(core2)
    receipts2 = receipts_from_events(events_all)
    state2 = engine_state(ledger2, events_all, receipts2)
    index2 = index_from_events(events_all)
    text2 = passage_text(control2, ledger2, state2, receipts2, list(index2), budget,
                         dropped=archived_without_slot(events_all, index2))
    return {'presented': {1: text1, 2: text2}, 'package': package2,
            'index': {1: index1, 2: index2}, 'ledger': {1: ledger1, 2: ledger2},
            'dropped': {'round1_entries': len(work['entries1']) - len(kept1),
                        'round2_writes': len(work['revisions']) - len(kept2)}}


RANK = {'fact': 0, 'verification': 1, 'decision': 2, 'requirement': 3, 'constraint': 4}


def fit(make_core, events: list, chosen: list, excerpt_items: list, base: list, entries: list,
        budget: int):
    """Shrink to the budget: whole sources, then excerpts, then low-value entries.

    Each attempt rebuilds a store, so a rejected budget writes nothing durable.
    ``base`` are entries already current from round 1; ``entries`` are this
    round's writes. Invalidation writes are never dropped: a dropped
    invalidation would re-present a fact the model retracted.
    """
    sources, excerpts, writes, kept = list(chosen), list(excerpt_items), list(entries), list(base)
    rows = [{'id': event.id, 'seq': index + 1, 'kind': event.kind, 'payload': event.payload,
             'observed_at': event.observed_at} for index, event in enumerate(events)]
    by_id = {row['id']: row for row in rows}
    now = max((row['observed_at'] for row in rows if row.get('observed_at')), default=None)

    def live(value):
        # A write can be expired the moment it lands (its condition fires inside
        # the very prefix it cites); such an entry is written but never current.
        return (value.status == 'active'
                and not entry_expired({'status': value.status, 'valid_until': value.valid_until,
                                       'invalid_when': value.invalid_when,
                                       'sources': value.sources}, rows, now, by_id=by_id))

    def refs():
        live_entries = [entry for entry in kept if live(entry)] + \
                       [write for write in writes if live(write)]
        return tuple(f'{entry.id}@{entry.expected_revision + 1 if entry.expected_revision is not None else 1}'
                     for entry in live_entries)

    while True:
        core, _ = make_core(events)
        try:
            view = core.prepare(core.capture(), Selection(source_ids=tuple(sources),
                                                          excerpts=tuple(excerpts),
                                                          new_understandings=tuple(kept) + tuple(writes),
                                                          understanding_refs=refs()),
                                producer='live-model', limits=Limits(max_view_bytes=budget))
            return core, view, list(kept)
        except WSCError as error:
            if 'view_byte_budget_exhausted' not in str(error):
                raise
            if sources:
                sources.pop()
                continue
            if excerpts:
                excerpts.pop()
                continue
            active = [index for index, write in enumerate(writes) if live(write)]
            if active and (kept or len(active) > 1):
                _, worst = min((RANK.get(writes[index].kind, 0), index) for index in active)
                writes.pop(worst)
                continue
            if kept and (active or len(kept) > 1):
                worst = min(range(len(kept)),
                            key=lambda index: (RANK.get(kept[index].kind, 0), index))
                kept.pop(worst)
                continue
            raise


THIN_PATH = re.compile(r'[A-Za-z0-9_./\\-]+\.(?:py|js|mjs|ts|tsx|json|md|yml|yaml|txt|cjs)')
THIN_KINDS = ('constraint', 'requirement', 'decision', 'verification', 'fact')
THIN_RANK = {'fact': 0, 'verification': 1, 'decision': 2, 'requirement': 3, 'constraint': 4}


def event_path(event) -> str | None:
    if event is None:
        return None
    payload = event.payload or {}
    if payload.get('name') not in ('edit', 'write'):
        return None
    args = payload.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    if not isinstance(args, dict):
        return None
    for key in ('path', 'file_path', 'target_file', 'notebook_path'):
        if isinstance(args.get(key), str) and args[key]:
            return args[key]
    return None


def event_edit(event) -> dict | None:
    """Edit payload as the event recorded it; path only is not enough to continue."""
    if event is None:
        return None
    payload = event.payload or {}
    if payload.get('name') not in ('edit', 'write'):
        return None
    args = payload.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    if not isinstance(args, dict):
        return None
    path = next((args[key] for key in ('path', 'file_path', 'target_file', 'notebook_path')
                 if isinstance(args.get(key), str) and args[key]), None)
    if path is None:
        return None
    new = args.get('new_string')
    if not isinstance(new, str):
        new = args.get('content') if isinstance(args.get('content'), str) else ''
    old = args.get('old_string') if isinstance(args.get('old_string'), str) else ''
    return {'path': path, 'old': old, 'new': new}


def receipts_from_events(events: list) -> list:
    """Mechanical J checks: which edit each later test-like check actually covers."""
    failed = {event.call_id for event in events
              if event.kind == 'result' and re.search(
                  r'(?i)\b(error|exception|permissionerror|failed|traceback)\b', event.text or '')}
    calls, edits, checks = {}, [], []
    for index, event in enumerate(events):
        if event.kind == 'call':
            calls[event.call_id] = event
        edit = event_edit(event)
        if edit is not None and event.call_id not in failed:
            edits.append({'at': index, 'path': edit['path'], 'text': edit['new']})
        command = event_command(calls.get(event.call_id))
        if (event.kind == 'result' and cargs_test(command)):
            body = event.text or ''
            first = next((line.strip() for line in body.split('\n') if line.strip()), '')[:120]
            checks.append({'at': index, 'command': command[:80], 'result': first,
                           'synthetic': 'synthetic' in (command + ' ' + body).lower()})
    receipts = []
    for edit in edits:
        later = min([other['at'] for other in edits
                     if other['path'] == edit['path'] and other['at'] > edit['at']], default=None)
        window = [check for check in checks if check['at'] > edit['at']
                  and (later is None or check['at'] < later)]
        receipt = {'path': edit['path'], 'edit': edit['at'] + 1, 'edit_text': edit.get('text', ''),
                   'check': None, 'command': '', 'result': '', 'stale': False, 'synthetic': False}
        if window:
            receipt.update(check=window[-1]['at'] + 1, command=window[-1]['command'],
                           result=window[-1]['result'], synthetic=window[-1]['synthetic'])
            receipt['stale'] = later is not None
        receipts.append(receipt)
    return receipts


def archive_from_events(events: list) -> list:
    """Every source of the region is archived; the model only sees an index over it."""
    rows = []
    for index, event in enumerate(events):
        text = event.text or ''
        if not text.strip():
            continue
        rows.append({'key': f'e{index + 1}', 'source_id': event.id, 'message': index + 1,
                     'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()})
    return rows


def index_from_events(events: list, limit: int = 20) -> list:
    """Discovery surface over every source; the bytes stay in the cold store."""
    calls, rows = {}, []
    for event in events:
        if event.kind == 'call':
            calls[event.call_id] = event
    for index, event in enumerate(events):
        text = (event.text or '').strip()
        if not text.strip():
            continue
        first = next((line.strip() for line in text.split('\n') if line.strip()), '')[:72]
        path, command = event_path(event), event_command(event)
        payload = event.payload or {}
        if path is not None:
            args = payload.get('arguments')
            try:
                args = args if isinstance(args, dict) else json.loads(args or '{}')
            except ValueError:
                args = {}
            changed = ' '.join(str(args.get(key, '')) for key in ('old_string', 'new_string')
                               if isinstance(args.get(key), str))
            terms = terms_of(changed) or terms_of(path)
            label, rank, kind = f'edit {path}', 2, 'edit'
        elif event.kind == 'call' and payload.get('name') in ('read', 'write', 'edit'):
            args = payload.get('arguments')
            try:
                args = args if isinstance(args, dict) else json.loads(args or '{}')
            except ValueError:
                args = {}
            target = next((args.get(key) for key in ('path', 'file_path', 'target_file')
                           if isinstance(args.get(key), str)), '')
            terms = terms_of(target)
            if payload.get('name') == 'read':
                # Reads are recomputable navigation; the result row carries the
                # evidence, so a read must not spend an edit slot of the index.
                label, rank, kind = f'read {target}', 5, 'read'
            else:
                label, rank, kind = f'{payload.get("name")} {target}', 2, 'edit'
        elif event.kind == 'call' and command:
            terms = terms_of(command)
            label, rank, kind = f'cmd {command[:80]}', 4, 'cmd'
        elif event.kind == 'result' and re.search(r'(?i)error|exception|permissionerror|failed|traceback', text):
            terms = terms_of(text)
            label, rank, kind = f'error {first}', 0, 'error'
        elif event.kind == 'result' and cargs_test(event_command(calls.get(event.call_id))):
            terms = terms_of(text)
            label, rank, kind = f'test {first}', 1, 'test'
        elif event.kind == 'message' and event.role == 'user':
            continue
        elif event.kind == 'message':
            checked = re.search(r'(?i)verif|check|passed|failed|test|edit', text)
            stateful = re.search(r'\d|\.py|\.js|/', text)
            terms = terms_of(text)
            # The position stays visible so a note can be read as old without
            # the engine deciding which note is still true.
            label, rank, kind = (f'm{index + 1} note {first}',
                                 1 if checked else 3 if stateful else 5, 'note')
        elif event.kind == 'result' and VALUE_SIGNAL.search(text):
            terms = terms_of(text)
            label, rank, kind = f'value {first}', 2, 'value'
        elif event.kind == 'result':
            terms = terms_of(text)
            label, rank, kind = f'result {first}', 3, 'output'
        else:
            continue
        rows.append({'key': '', 'source_id': event.id, 'message': index + 1,
                     'label': label, 'rank': rank, 'kind': kind, 'terms': terms, 'text': text})
    # One burst repeats one result; one index entry is enough to discover it.
    seen, unique = set(), []
    for row in sorted(rows, key=lambda row: (row['rank'], row['message'])):
        fingerprint = (row['kind'], row['label'][:60], tuple(row['terms'][:3]))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(row)
    caps = {'error': 4, 'test': 4, 'edit': 5, 'value': 16, 'read': 2, 'cmd': 3,
            'note': 6, 'output': 5}
    # Every category present keeps one discovery slot before quotas fill up:
    # a cap must never be able to hide the only evidence of a kind.
    rows, used_ids = [], set()
    for kind in ('error', 'test', 'value', 'edit', 'note', 'output', 'cmd', 'read'):
        row = next((item for item in unique if item['kind'] == kind), None)
        if row is not None:
            rows.append(row)
            used_ids.add(id(row))
    counts = {}
    for row in rows:
        counts[row['kind']] = counts.get(row['kind'], 0) + 1
    for row in unique:
        if len(rows) >= limit:
            break
        if id(row) in used_ids:
            continue
        if counts.get(row['kind'], 0) >= caps[row['kind']]:
            continue
        counts[row['kind']] = counts.get(row['kind'], 0) + 1
        rows.append(row)
    rows.sort(key=lambda row: (row['rank'], row['message']))
    for number, row in enumerate(rows, 1):
        row['key'] = f'E{number}'
    return rows


def archived_without_slot(events: list, index: list) -> int:
    indexed = {row['source_id'] for row in index}
    return sum(1 for event in events
               if (event.text or '').strip() and event.id not in indexed
               and not (event.kind == 'message' and event.role == 'user'))


def thin_entry(raw: dict, *, entry_id: str, seq: int,
               revision: int = 1, status: str = 'active') -> dict | None:
    """No source pointer crosses the model boundary; the write position is its anchor."""
    text = ' '.join(str(raw.get('text') or '').split())
    if not text:
        return None
    if len(text) > 220:
        text = text[:219] + '…'
    kind = str(raw.get('kind') or 'fact')
    if kind not in THIN_KINDS:
        kind = 'fact'
    invalid = raw.get('invalid_when')
    return {'id': entry_id, 'rev': revision, 'ref': f'{entry_id}@{revision}', 'kind': kind,
            'text': text, 'sources': (), 'seq': seq,
            'invalid_when': invalid if isinstance(invalid, dict) else None,
            'status': status}


def thin_expire(entries: list, events: list, *, base: int = 0) -> None:
    """A file edit after an entry was written makes a file-bound claim false.

    In a later region, a newly written "before the edit" result is history, not
    a current verification: the edit it precedes is already in the past.
    """
    edits = [(index, path) for index, event in enumerate(events)
             if (path := event_path(event)) is not None]
    for entry in entries:
        if entry['status'] != 'active':
            continue
        if (base and entry['kind'] == 'verification'
                and re.search(r'(?i)before (the )?edit', entry['text']) and edits):
            entry['status'] = 'invalidated'
            entry['expired_at'] = edits[-1][0] + 1
            continue
        # Only a result about a file is falsified by editing it. A decision that
        # mentions the path, or a constraint about the signature, still holds.
        paths = set(THIN_PATH.findall(entry['text'])) if entry['kind'] == 'verification' else set()
        if (entry.get('invalid_when') or {}).get('file_changed'):
            paths.add(entry['invalid_when']['file_changed'])
        for at, path in edits:
            if at > entry['seq'] and path in paths:
                entry['status'] = 'invalidated'
                entry['expired_at'] = at + 1
                break


def thin_apply(entries: list, raw: dict, items: list, *, base: int, next_id: int) -> int:
    """Replace a current entry in place by revision, then append new entries."""
    by_id = {entry['id']: entry for entry in entries}
    seq = base + max(0, len(items) - 1)
    for item in (raw.get('replaces', []) or [])[:8]:
        match = re.match(r'(.+)@(\d+)$', str(item.get('ref', '')))
        if not match or match.group(1) not in by_id:
            continue
        old = by_id[match.group(1)]
        if old['status'] != 'active':
            continue
        replacement = thin_entry(item, entry_id=old['id'], seq=seq, revision=old['rev'] + 1)
        if replacement is None:
            continue
        old['status'] = 'superseded'
        entries.append(replacement)
        by_id[replacement['id']] = replacement
    for item in (raw.get('entries', []) or [])[:8]:
        entry = thin_entry(item, entry_id=f't{next_id}', seq=seq)
        if entry is not None:
            entries.append(entry)
            next_id += 1
    for ref in raw.get('drop', []) or []:
        match = re.match(r'(.+)@(\d+)$', str(ref))
        if match and match.group(1) in by_id and by_id[match.group(1)]['status'] == 'active':
            by_id[match.group(1)]['status'] = 'superseded'
    return next_id


def thin_state(raw: dict, receipts: list, entries: list) -> dict:
    """Model slots clamped; the engine appends the gaps the receipts prove."""
    value = raw.get('state') if isinstance(raw.get('state'), dict) else {}
    state = {}
    for key in ('done', 'open', 'next', 'unknown'):
        rows = value.get(key)
        state[key] = [row.strip()[:160] for row in rows if isinstance(row, str) and row.strip()][:6] \
            if isinstance(rows, list) else []
    if state['open'] and not state['next']:
        state['unknown'].append('next action not recorded for the open item')
    for receipt in receipts:
        if receipt['check'] is None:
            state['unknown'].append(f"no post-edit verification for {receipt['path']} after edit #{receipt['edit']}")
        elif receipt['stale']:
            state['unknown'].append(f"{receipt['path']} changed after the check at #{receipt['check']}")
    for entry in entries:
        if entry['status'] != 'active':
            continue
        if entry['kind'] == 'verification' and not re.search(
                r'(?i)after (the )?edit|before (the )?edit|version|#\d+|m\d+', entry['text']):
            state['unknown'].append(f"verification is not version-bound: {entry['text'][:80]}")
    state['unknown'] = list(dict.fromkeys(state['unknown']))[:6]
    evidence = [row for row in state['unknown'] if row.startswith('no verification evidence for ')]
    if len(evidence) > 1:
        rest = [row for row in state['unknown'] if row not in evidence]
        labels = [row[len('no verification evidence for '):] for row in evidence]
        state['unknown'] = rest + ['no verification evidence for: ' + '; '.join(labels)]
    return state


STATE_STOP = {'round', 'change', 'file', 'source', 'test', 'tests', 'pass', 'result', 'ok',
              'continue', 'latest', 'current', 'after', 'before', 'edit', 'edits', 'path',
              'requirement', 'requirements', 'policy', 'the', 'and', 'for', 'with'}
STATE_WORDS = ('async', 'await', 'synchronous', 'asynchronous')
STATE_NEGATION = re.compile(
    r'(?i)\b(not|never|no longer|unverified|instead|rather|without|failed|missing)\b')


def significant_terms(text: str) -> list:
    found = list(terms_of(text or '', limit=12))
    for quoted in re.findall(r'"([^"\n]{2,48})"', text or ''):
        if quoted not in found:
            found.append(quoted)
    lowered = (text or '').lower()
    for word in STATE_WORDS:
        if re.search(r'\b' + word + r'\b', lowered):
            found.append(word)
    return [term for term in dict.fromkeys(found)
            if len(term) >= 3 and term.lower() not in STATE_STOP]


REQ_STOP = {'requirement', 'must', 'should', 'then', 'with', 'from', 'that', 'this',
            'have', 'also', 'only', 'will', 'using', 'use', 'the', 'and', 'for', 'not',
            'exact', 'current', 'version', 'file', 'files', 'continue', 'please'}


def requirement_terms(text: str) -> list:
    """Anchors from the requirement itself: literals, quotes and identifier words.

    Plain identifiers such as ``retries`` are decision-relevant and must stay
    anchors; borrowing words from unrelated facts is what made a placeholder
    edit look like a match.
    """
    found = significant_terms(text)
    for name, value in re.findall(
            r'\b([a-z_][a-z0-9_]*)\s+(?:to|=)\s+([a-z0-9_./-]+)', (text or '').lower()):
        for term in (name, value):
            if term in REQ_STOP or term in STATE_STOP or term in found:
                continue
            found.append(term)
    return found


def _fact_terms(text: str) -> set:
    """Specific literals from a fact, skipping negated clauses.

    A ledger often states the failure itself ("wrote X, not Y"). Treating the
    quoted placeholder as a satisfying value would turn a known failure into
    a false "done"; clauses with negation are therefore excluded.
    """
    found = set()
    for clause in re.split(r'[,;.]', text or ''):
        if STATE_NEGATION.search(clause):
            continue
        for term in significant_terms(clause):
            if ' ' in term or '\t' in term:
                continue
            if (term.isupper() or re.search(r'\d', term)
                    or term.lower() in STATE_WORDS or THIN_PATH.fullmatch(term)
                    or term.startswith(('src/', 'tests/', 'docs/'))):
                found.add(term)
    return found


def _entry_authority(entry: dict, roles: dict) -> str | None:
    sources = entry.get('sources') or ()
    values = [roles.get(source) for source in sources]
    values = [value for value in values if value]
    return 'assistant' if values and all(value == 'assistant' for value in values) else None


def _state_tag(text: str, authority: str | None) -> str:
    return f'({authority}-originated) {text}' if authority == 'assistant' else text


def _state_quote(text: str) -> str:
    value = ' '.join((text or '').split())
    return f'"{value[:40]}"' if value else '(empty)'


def _state_clean(text: str) -> str:
    """Drop a model/control label; the renderer adds the ledger label itself."""
    value = ' '.join((text or '').split())
    return re.sub(r'(?i)^(requirement|constraint|change)\s*:\s*', '', value)


def _state_brief(text: str, limit: int = 100) -> str:
    value = ' '.join((text or '').split())
    if len(value) <= limit:
        return value.rstrip(' ;,')
    return value[:limit].rsplit(' ', 1)[0].rstrip(' ;,') + '…'


def recent_receipts(receipts: list) -> list:
    """One receipt per path: the latest edit and the check that followed it."""
    seen, kept = set(), []
    for receipt in reversed(receipts):
        if receipt['path'] in seen:
            continue
        seen.add(receipt['path'])
        kept.append(receipt)
    return list(reversed(kept))


def engine_state(entries: list, events: list, receipts: list) -> dict:
    """Engine-owned work status for WSC/lean; no model call and no extra write.

    The ledger keeps conclusions. This projection keeps the relations a resume
    decision needs: the latest edit payload, whether it still matches an active
    requirement, what the check covers, and who originated the requirement.
    """
    roles = {event.id: getattr(event, 'role', None) for event in events
             if getattr(event, 'kind', None) == 'message'}
    failed = {event.call_id for event in events
              if event.kind == 'result' and re.search(
                  r'(?i)\b(error|exception|permissionerror|failed|traceback)\b', event.text or '')}
    edits, by_path = [], {}
    for index, event in enumerate(events):
        edit = event_edit(event)
        if edit is None or event.call_id in failed:
            continue
        row = {'at': index + 1, 'path': edit['path'], 'old': edit['old'], 'new': edit['new']}
        edits.append(row)
        by_path[edit['path']] = row
    state = {'done': [], 'open': [], 'next': [], 'unknown': []}
    gap_keys = set()
    active = [entry for entry in entries if entry.get('status', 'active') == 'active']
    requirements = [entry for entry in active
                    if entry.get('kind') in ('requirement', 'constraint')]
    control_texts = []
    for event in events:
        if event.kind == 'message' and getattr(event, 'role', None) == 'user':
            text = ' '.join((event.text or '').split())
            if text:
                control_texts.append(text)
    control_texts = list(dict.fromkeys(control_texts))
    control_no = {text: number for number, text in enumerate(control_texts, 1)}
    # The lean ledger may omit a user requirement. The control messages are the
    # authority for goals, so synthesize the latest effective requirement per
    # path unless an active ledger requirement already carries it.
    covered = set()
    for entry in requirements:
        covered.update(significant_terms(entry.get('text') or ''))
    for entry in active:
        if entry.get('kind') not in ('fact', 'decision'):
            continue
        if not re.search(r'(?i)\b(pending|remaining|todo)\b', entry.get('text') or ''):
            continue
        terms = set(significant_terms(entry.get('text') or ''))
        if terms & covered:
            continue
        requirements.append(entry)
        covered.update(terms)
    messages_by_path = {}
    for position, event in enumerate(events):
        if event.kind != 'message' or getattr(event, 'role', None) != 'user':
            continue
        text = ' '.join((event.text or '').split())
        if not text or text.rstrip('.').lower() in ('continue',):
            continue
        paths = THIN_PATH.findall(text)
        if not paths:
            continue
        messages_by_path.setdefault(paths[0], []).append((position, event, text))
    for path, rows in messages_by_path.items():
        changed = next((index for index, (_, _, text) in enumerate(rows)
                        if re.search(r'(?i)\b(change|now|instead|no longer|replace)\b', text)),
                       None)
        kept = rows[changed:] if changed is not None else rows
        for position, event, text in kept:
            terms = set(significant_terms(text))
            if terms & covered:
                continue
            requirements.append({'kind': 'requirement', 'text': text,
                                 'status': 'active', 'sources': (event.id,), 'seq': position,
                                 'control_no': control_no.get(text)})
            covered.update(terms)
    for entry in requirements:
        text = _state_clean(entry.get('text') or '').rstrip('. ')
        if not text:
            continue
        # A requirement the user stated is already quoted verbatim above; the
        # state only needs its position there, not a third copy of the text.
        brief = (f"req#{entry['control_no']}" if entry.get('control_no')
                 else _state_brief(text, 160))
        terms = list(dict.fromkeys(requirement_terms(text)))
        paths = THIN_PATH.findall(text)
        path = paths[0] if paths else None
        edit = by_path.get(path) if path else (edits[-1] if edits else None)
        authority = _entry_authority(entry, roles)
        if edit is None:
            where = f'no edit to {path} found' if path else 'no target file identified'
            state['open'].append(_state_tag(f'{brief}; {where}', authority))
            continue
        def matches(candidate):
            new = (candidate.get('new') or '').lower()
            found = [term for term in terms
                     if term.lower() in new and term.lower() != (path or '').lower()]
            if (re.search(r'(?i)\bsynchronous\b|\bsync\b', text)
                    and re.search(r'(?i)(?<!async )\bdef\s+', new)):
                found.append('def')
            return found
        matched = matches(edit)
        earlier = [candidate for candidate in edits
                   if (not path or candidate['path'] == path) and candidate['at'] < edit['at']
                   and matches(candidate)]
        receipt = next((row for row in receipts
                        if row.get('path') == edit['path'] and row.get('edit') == edit['at']), None)
        if matched:
            if receipt and receipt.get('check'):
                detail = (receipt.get('result') or '').rstrip('. ')[:60]
                command = (receipt.get('command') or '')[:40]
                state['done'].append(_state_tag(
                    f"{brief} (edit #{edit['at']}, check #{receipt['check']}"
                    + (f" {command}: {detail}" if command or detail else '') + ')', authority))
            else:
                state['open'].append(_state_tag(
                    f"{brief}; edit #{edit['at']} matches but has no post-edit check", authority))
        elif earlier:
            state['unknown'].append(_state_tag(
                f"{brief}; latest edit #{edit['at']} to {edit['path']} wrote "
                f"{_state_quote(edit['new'])}; earlier edit #{earlier[-1]['at']} matched; "
                'current state unverified', authority))
        else:
            state['open'].append(_state_tag(
                f"{brief}; latest edit to {edit['path']} wrote {_state_quote(edit['new'])}",
                authority))
        # A check that ran but cannot support the claim is one gap, stated once.
        if receipt and receipt.get('check'):
            for kind, row in (('synthetic', f"check at #{receipt['check']} is synthetic; "
                                            f"it does not verify {edit['path']}"),
                              ('stale', f"{edit['path']} changed after the check at "
                                        f"#{receipt['check']}")):
                key = (edit['path'], receipt['check'], kind)
                if receipt.get(kind) and key not in gap_keys:
                    gap_keys.add(key)
                    state['unknown'].append(row)
    next_position, next_value, next_role = None, '', None
    for position in range(len(events) - 1, -1, -1):
        event = events[position]
        if getattr(event, 'kind', None) != 'message':
            continue
        match = re.search(r'(?i)\bnext(?:\s+(?:step|action))?\s*:\s*(.+?)(?:\.\s|\.$|$)',
                          event.text or '')
        if match:
            next_position = position
            next_value = ' '.join(match.group(1).split())[:120]
            next_role = getattr(event, 'role', None)
            break
    if next_value:
        # A later user change that touches the same terms revokes the recorded
        # next action; it stays visible as unknown, never as a recommendation.
        terms = set(significant_terms(next_value))
        stale = ''
        for event in events[next_position + 1:]:
            if (getattr(event, 'kind', None) != 'message'
                    or getattr(event, 'role', None) != 'user'):
                continue
            text = ' '.join((event.text or '').split())
            if not re.search(r"(?i)\b(change|changed|instead|no longer|do not|don't|"
                             r'revert|undo|replace|cancel)\b', text):
                continue
            if terms & set(significant_terms(text)):
                stale = text[:120]
                break
        if stale:
            state['unknown'].append(
                f'recorded next action may be stale after a later change: {stale}')
        else:
            suffix = ' (assistant-originated)' if next_role == 'assistant' else ''
            state['next'].append(f'{next_value}{suffix}')
    if state['next']:
        # The next action has one home. A pending fact that became open would
        # state the same relation twice.
        value = re.sub(r'\s*\([^)]*originated\)$', '', state['next'][0])[:60].lower()
        state['open'] = [row for row in state['open'] if value not in row.lower()]
    if state['open'] and not state['next']:
        state['unknown'].append('next action not recorded for the open item')
    for key in ('done', 'open', 'next', 'unknown'):
        state[key] = list(dict.fromkeys(row[:200] for row in state[key]))[:6]
    return state


def thin_call(model: Model, items: list, rows: list, state: dict, round_number: int,
              *, label: str) -> dict:
    body = numbered(items)
    if round_number == 1:
        prompt = THIN_CREATE
    else:
        ledger = '\n'.join(f"- [{row['ref']}] {row['kind']}: {row['text']}" for row in rows) or '- (empty)'
        state_text = '\n'.join(f"{key}: {'; '.join(value)}" for key, value in state.items() if value) \
            or '(empty)'
        prompt = THIN_UPDATE + '\n\nCurrent ledger:\n' + ledger + '\n\nCurrent state:\n' + state_text
    output = model.chat([{'role': 'user', 'content': body + '\n\n' + prompt}],
                        max_tokens=16384, label=label)
    parsed = json_object(output['text'])
    if parsed is None:
        output = model.chat([
            {'role': 'user', 'content': body + '\n\n' + prompt},
            {'role': 'assistant', 'content': output['text']},
            {'role': 'user', 'content': 'Return only the JSON object, no prose, no fences.'},
        ], max_tokens=16384, label=label + '-retry')
        parsed = json_object(output['text']) or {}
    return parsed if isinstance(parsed, dict) else {}



def thin_model_work(model: Model, case: dict) -> dict:
    """Thin layer model work: one call per round, bounded semantic slots only."""
    adapter = CodexCheckpointAdapter()
    items1, items2 = case['items'], case['round2']['items']
    items_all = items1 + items2
    events1 = adapter.import_items(items1, thread_id=case['case'], observed_at=observed_at(0, len(items1)))
    events2 = adapter.import_items(items2, thread_id=case['case'], start_ordinal=len(items1),
                                   observed_at=observed_at(len(items1), len(items2)))
    events_all = events1 + events2
    control = [event.text for event in events_all
               if event.kind == 'message' and event.role == 'user' and (event.text or '').strip()]
    tag = case['case']

    raw1 = thin_call(model, items1, [], {}, 1, label=f'{tag}:thin-r1')
    entries, next_id = [], 1
    next_id = thin_apply(entries, raw1, items1, base=0, next_id=next_id)
    thin_expire(entries, events1, base=0)
    repaired1 = repair_identifiers(entries, events1)
    receipts1 = receipts_from_events(events1)
    state1 = thin_state(raw1, receipts1, entries)
    index1 = index_from_events(events1)
    rounds1 = {'entries': [dict(entry) for entry in entries], 'state': state1,
               'archive': archive_from_events(events1), 'index': index1,
               'dropped': archived_without_slot(events1, index1)}

    rows = [{'ref': entry['ref'], 'kind': entry['kind'], 'text': entry['text']}
            for entry in entries if entry['status'] == 'active']
    index2 = index_from_events(events_all)
    raw2 = thin_call(model, items2, rows, state1, 2, label=f'{tag}:thin-r2')
    next_id = thin_apply(entries, raw2, items2, base=len(items1), next_id=next_id)
    thin_expire(entries, events_all, base=len(items1))
    repaired2 = repair_identifiers(entries, events_all)
    receipts2 = receipts_from_events(events_all)
    state2 = thin_state(raw2, receipts2, entries)
    return {'events1': events1, 'events2': events2, 'events_all': events_all,
            'control': control, 'entries': entries, 'next_id': next_id,
            'rounds': {1: rounds1, 2: {'entries': [dict(entry) for entry in entries],
                                       'state': state2, 'archive': archive_from_events(events_all),
                                       'index': index2,
                                       'dropped': archived_without_slot(events_all, index2)}},
            'receipts': {1: receipts1, 2: receipts2},
            'raw': {1: raw1, 2: raw2},
            'repair': {1: repaired1, 2: repaired2},
            'audit': anchor_audit(entries, events_all)}


def passage_text(control: list, entries: list, state, receipts: list, index: list,
                 budget: int, blocked: list = (), dropped: int = 0,
                 values: list = (), next_banner: bool = False) -> str:
    return render_passage(control=control, ledger=entries, state=state, receipts=receipts,
                          index=index, values=values, budget=budget, blocked=blocked,
                          dropped=dropped, next_banner=next_banner)


def thin_render(work: dict, round_number: int, budget: int) -> str:
    rounds = work['rounds'][round_number]
    entries = list(rounds['entries'])
    blocked = []
    for entry in entries:
        if entry['status'] == 'invalidated':
            blocked.extend([entry['text'], entry['text'].rstrip('.')])
            # A state slot may restate only the version phrase, not the whole
            # entry; block "<Vn> checked" so an invalidated check cannot return
            # as current through model-authored state or a discovery label.
            blocked.extend(re.findall(r'V\d+ checked', entry['text']))
    return passage_text(work['control'], entries, rounds['state'],
                        work['receipts'][round_number], list(rounds['index']), budget, blocked,
                        rounds.get('dropped', 1 if rounds['index'] else 0))


def thin_present(case: dict, root: Path, work: dict, round_number: int, budget: int) -> dict:
    text = thin_render(work, round_number, budget)
    directory = root / 'thin-evidence'
    directory.mkdir(parents=True, exist_ok=True)
    locators, verified = {}, {}
    for item in work['rounds'][round_number]['archive']:
        path = directory / (item['text_sha256'] + '.txt')
        raw = item['text'].encode()
        if not path.is_file():
            path.write_bytes(raw)
        locators[item['key']] = {'source_id': item['source_id'], 'file_path': str(path),
                                 'sha256': item['text_sha256'], 'message': item['message']}
        verified[item['key']] = (path.is_file()
                                 and hashlib.sha256(path.read_bytes()).hexdigest() == item['text_sha256'])
    return {'presented': text, 'bytes': len(text.encode()), 'evidence': locators,
            'index': work['rounds'][round_number]['index'],
            'verified': bool(verified) and all(verified.values())}


def matched_present(case: dict, root: Path, work: dict, target: int, upper: int,
                    tag: str = 'wsc-matched') -> tuple:
    """Find a view budget whose rendered checkpoint bytes match ``target``.

    The budget bounds the view body; the rendered checkpoint adds its state
    frame, locators and archive index. Byte-matching therefore searches the
    budget until the rendering, not the body, matches the native checkpoint.
    Presentation makes no model calls, so every probe is free.
    """
    low, high, best = 1024, upper, None
    for attempt in range(12):
        mid = (low + high) // 2
        try:
            result = present(case, root, mid, tag=f'{tag}-{mid}', work=work)
        except WSCError as error:
            if 'view_byte_budget_exhausted' not in str(error):
                raise
            low = mid
            continue
        size = len(result['presented'][2].encode())
        if best is None or abs(size - target) < abs(best[2] - target):
            best = (mid, result, size)
        if size < target:
            low = mid
        else:
            high = mid
        if high - low <= 64:
            break
    return best


RETRIEVE_PROMPT = '\n'.join([
    'Only the index below survived compaction; the original messages are in a cold store.',
    'For each question, name the keys whose stored text answers it. Return only JSON:',
    '{"answers":[{"question":"<copy the question>","keys":["E<number>"]}]}',
    'Rules: - Use only keys present in the index. - If no key applies, return an empty list.',
    '- Do not answer the questions from memory; select keys only. Output only the JSON object.',
])


def retrieval_probe(model: Model, case: dict, index: list, label: str) -> dict:
    """One model call, retried once with a trimmed index; select cold keys."""
    oracle = case['round2']['oracle']
    evidence = {fact['id']: (fact.get('needle') or fact['text']) for fact in oracle['evidence']}
    questions = []
    for probe in case['round2']['probes']:
        expected = [fact for fact in probe['expects'] if fact in evidence]
        if expected:
            questions.append({'question': probe['question'], 'expects': expected[0]})
    if not questions:
        return {'questions': 0}
    list_questions = '\n'.join(f"{number}. {item['question']}"
                               for number, item in enumerate(questions, 1))
    attempts, output, surface = [], None, index

    def ask(rows, budget, suffix=''):
        body = index_text(rows) + '\n\nQuestions:\n' + list_questions + '\n\n' + RETRIEVE_PROMPT
        result = model.chat([{'role': 'user', 'content': body}], max_tokens=budget,
                            label=label + suffix)
        attempts.append(result)
        return result

    output = ask(index, 4096)
    parsed = json_object(output['text']) or {}
    # An empty reply is often a reasoning budget cut, not a miss: retry the
    # same questions over a shorter index with the full budget.
    if not (isinstance(parsed.get('answers'), list) and parsed['answers']):
        surface = index[:12] if len(index) > 12 else index
        output = ask(surface, 8192, '-retry')
        parsed = json_object(output['text']) or {}
    answers = parsed.get('answers') if isinstance(parsed.get('answers'), list) else []
    by_key = {row['key']: row for row in surface}
    hits, chosen = 0, []
    for position, item in enumerate(questions):
        answer = next((row for row in answers if isinstance(row, dict)
                       and str(row.get('question', '')).strip() == item['question']), None)
        if answer is None and position < len(answers):
            answer = answers[position] if isinstance(answers[position], dict) else None
        keys = [key for key in (answer or {}).get('keys', []) if key in by_key]
        chosen.append({'question': item['question'], 'keys': keys})
        needle = evidence[item['expects']]
        if any(needle in by_key[key]['text'] for key in keys):
            hits += 1
    usage = {name: sum(attempt['usage'].get(name, 0) for attempt in attempts)
             for name in ('prompt_tokens', 'completion_tokens')}
    return {'questions': len(questions), 'hits': hits,
            'hit_rate': round(hits / len(questions), 4), 'chosen': chosen,
            'attempts': [{'finish': attempt.get('finish'), 'chars': len(attempt['text'])}
                         for attempt in attempts],
            'usage': usage, 'index_rows': len(surface)}



TOKEN_NOISE = {'file_path', 'old_string', 'new_string', 'arguments', 'command', 'content',
               'name', 'output', 'input', 'payload', 'text', 'path', 'type', 'call_id', 'id'}
ANCHOR_WINDOW = 64


def anchor_facts(entries: list, events: list, window: int = ANCHOR_WINDOW) -> dict:
    """Nearest source for each entry by token overlap, scanned in a bounded window.

    The window keeps the pass linear in the round, not in the whole transcript.
    A source literal the entry failed to quote is recorded for mechanical repair.
    """
    texts = [event.text or '' for event in events]
    lowered = [text.lower() for text in texts]
    facts = {}
    for entry in entries:
        if entry.get('status') != 'active':
            continue
        seq = entry.get('seq')
        low = max(0, (seq or 0) - window)
        high = min(len(events), (seq or 0) + window + 1)
        if not any(lowered[low:high]):
            low, high = 0, len(events)
        tokens = {token.lower() for token, _ in needle_tokens(entry['text'])}
        best = max(((sum(1 for token in tokens if token in lowered[index]), index + 1)
                    for index in range(low, high)), default=(0, None))
        missing = []
        if best[1] and entry['kind'] in ('decision', 'verification'):
            missing = [term for term in terms_of(texts[best[1] - 1])
                       if term not in entry['text'] and term.lower() not in TOKEN_NOISE][:4]
        facts[entry['ref']] = {'message': best[1] if best[0] else None,
                               'overlap': best[0], 'missing': missing}
    return facts


def anchor_audit(entries: list, events: list) -> dict:
    """Engine-only anchor and literal audit; never shown to the model."""
    facts = anchor_facts(entries, events)
    gaps = [{'ref': ref, 'missing': fact['missing']}
            for ref, fact in facts.items() if fact['missing']]
    return {'anchors': {ref: {'message': fact['message'], 'overlap': fact['overlap']}
                        for ref, fact in facts.items()},
            'verbatim_gaps': gaps[:5]}


def repair_identifiers(entries: list, events: list) -> list:
    """Copy source literals the entry dropped; mechanical, no model call.

    Only literals already verified present in the anchored source are appended;
    nothing is generated or corrected beyond that.
    """
    repaired = []
    for ref, fact in anchor_facts(entries, events).items():
        if not fact['missing']:
            continue
        entry = next(row for row in entries if row['ref'] == ref)
        clause = ' Exact source tokens: ' + ', '.join(fact['missing']) + '.'
        if len(entry['text']) + len(clause) > 320:
            continue
        entry['text'] = entry['text'].rstrip('.') + '.' + clause
        entry['repaired'] = fact['missing']
        repaired.append({'ref': ref, 'tokens': fact['missing']})
    return repaired


def prune_archive(directory: Path, keep: set, limit: int = 256) -> int:
    """Bounded cold store: oldest evidence beyond the limit and unreferenced goes first."""
    files = sorted(directory.glob('*.txt'), key=lambda path: path.stat().st_mtime)
    excess = max(0, len(files) - limit)
    removed = 0
    for path in files:
        if removed >= excess:
            break
        if path.name in keep:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def matched_thin(case: dict, work: dict, target: int, upper: int) -> tuple:
    low, high, best = 1024, upper, None
    for _ in range(12):
        mid = (low + high) // 2
        text = thin_render(work, 2, mid)
        size = len(text.encode())
        if best is None or abs(size - target) < abs(best[1] - target):
            best = (mid, size, text)
        if size < target:
            low = mid
        else:
            high = mid
        if high - low <= 64:
            break
    return best


def verify_evidence(package: dict) -> dict:
    verified = {}
    locators = dict(package.get('evidence', {}))
    locators.update(package.get('excerpt_evidence', {}))
    for key, locator in locators.items():
        path = Path(locator['file_path'])
        try:
            verified[key] = (path.is_file()
                             and hashlib.sha256(path.read_bytes()).hexdigest() == locator['sha256'])
        except OSError:
            verified[key] = False
    return verified


def native_chain(model: Model, case: dict, budget: int) -> tuple:
    label = f'{case["case"]}:native-summary'
    native1 = run_native(model, case['items'], None, budget, label=label)
    native2 = run_native(model, case['round2']['items'], native1['presented'], budget, label=label)
    return native1, native2


def usage_by_arm(model: Model, case_name: str) -> dict:
    result = {arm: cost_module.empty() for arm in ('dsh_native', 'wsc', 'wsc_lean', 'wsc_thin')}
    for call in model.calls:
        if not call['label'].startswith(case_name + ':'):
            continue
        if ':retrieval-' in call['label']:
            continue
        arm = ('dsh_native' if ':native-' in call['label']
               else 'wsc_thin' if ':thin-' in call['label']
               else 'wsc_lean' if ':lean-' in call['label'] else 'wsc')
        bucket = result[arm]
        bucket['calls'] += 1
        cost_module.add(bucket, call['usage'])
    return result


def measure_case(case: dict, out: Path, model: Model) -> dict:
    root = out / case['case']
    root.mkdir(parents=True, exist_ok=True)
    region1 = {i: arms.flatten(item) for i, item in enumerate(case['items'])}
    region2 = {i: arms.flatten(item) for i, item in enumerate(case['items'] + case['round2']['items'])}
    region1_text = '\n'.join(region1.values())
    region2_text = '\n'.join(region2.values())
    budget = max(4096, int(len(region1_text.encode()) * DEFAULT_BUDGET_FRACTION))

    # Four chains overlap: native, thin, WSC and WSC-lean. Each WSC family
    # runs its rounds on its own pool so one slow endpoint cannot starve it.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix=case['case']) as inner, \
            ThreadPoolExecutor(max_workers=2, thread_name_prefix=case['case'] + '-lean') as lean_pool:
        native_future = inner.submit(native_chain, model, case, budget)
        thin_future = inner.submit(thin_model_work, model, case)
        lean_future = lean_pool.submit(wsc_lean_model_work, model, case, lean_pool)
        work = wsc_model_work(model, case, inner)
        native1, native2 = native_future.result()
        thin_work = thin_future.result()
        lean_work = lean_future.result()
    usage = usage_by_arm(model, case['case'])

    # The budget bounds the prepared body, not the rendered checkpoint. Search
    # for the body size whose rendering is half the region, so the working
    # point is stated in the same bytes it is compared in.
    half = max(1024, int(len(region2_text.encode()) * DEFAULT_BUDGET_FRACTION))
    product_budget, product, product_bytes = matched_present(case, root, work, half, budget)
    verified = verify_evidence(product['package'])
    lean_budget, lean_product, lean_bytes = matched_present(case, root, lean_work, half, budget,
                                                            tag='lean-half')
    lean_verified = verify_evidence(lean_product['package'])
    thin1 = thin_present(case, root, thin_work, 1, budget)
    thin2 = thin_present(case, root, thin_work, 2, budget)
    keep = {item['text_sha256'] + '.txt'
            for rnd in thin_work['rounds'].values() for item in rnd['archive']}
    pruned = prune_archive(root / 'thin-evidence', keep)
    thin_probe = retrieval_probe(model, case, thin2['index'], f'{case["case"]}:retrieval-thin')
    wsc_probe = retrieval_probe(model, case, product['index'][2], f'{case["case"]}:retrieval-wsc')
    lean_probe = retrieval_probe(model, case, lean_product['index'][2],
                                 f'{case["case"]}:retrieval-lean')

    # Head-to-head at matched bytes: the same model work, re-assembled until the
    # rendered checkpoint matches the native checkpoint's size. Every response
    # is cached and presentation makes no model calls, so the search is free.
    before_matched = usage_by_arm(model, case['case'])
    matched_budget, matched, matched_bytes = matched_present(case, root, work, native2['bytes'], budget)
    lean_matched_budget, lean_matched, lean_matched_bytes = matched_present(
        case, root, lean_work, native2['bytes'], budget, tag='lean-matched')
    thin_matched_budget, thin_matched_bytes, _ = matched_thin(case, thin_work, native2['bytes'], budget)
    thin_matched = thin_present(case, root, thin_work, 2, thin_matched_budget)
    after_matched = usage_by_arm(model, case['case'])
    matched_extra = {arm: {key: after_matched[arm][key] - before_matched[arm][key]
                           for key in after_matched[arm]} for arm in after_matched}
    matched_verified = verify_evidence(matched['package'])
    lean_matched_verified = verify_evidence(lean_matched['package'])

    materials = {'dsh_native': {1: native1['presented'], 2: native2['presented']},
                 'wsc': product['presented'],
                 'wsc_matched': matched['presented'],
                 'wsc_lean': lean_product['presented'],
                 'wsc_lean_matched': lean_matched['presented'],
                 'wsc_thin': {1: thin1['presented'], 2: thin2['presented']},
                 'wsc_thin_matched': {1: thin1['presented'], 2: thin_matched['presented']}}
    report = {}
    for name, presented in materials.items():
        current = claims_text(presented[2]) if name.startswith('wsc') else None
        report[name] = {
            'bytes': {1: len(presented[1].encode()), 2: len(presented[2].encode())},
            'ratio': {1: round(len(presented[1].encode()) / len(region1_text.encode()), 4),
                      2: round(len(presented[2].encode()) / len(region2_text.encode()), 4)},
            'scores': {1: score(case, 1, presented[1]),
                       2: score(case, 2, presented[2], current=current)},
        }
    report['dsh_native']['usage'] = usage['dsh_native']
    report['wsc']['usage'] = usage['wsc']
    report['wsc']['evidence'] = {'exported': len(product['package'].get('evidence', {}))
                                             + len(product['package'].get('excerpt_evidence', {})),
                                 'verified': bool(verified) and all(verified.values())}
    report['wsc_matched']['usage'] = matched_extra['wsc']
    report['wsc_matched']['evidence'] = {
        'exported': len(matched['package'].get('evidence', {}))
                    + len(matched['package'].get('excerpt_evidence', {})),
        'verified': bool(matched_verified) and all(matched_verified.values())}
    report['wsc_lean']['usage'] = usage['wsc_lean']
    report['wsc_lean']['evidence'] = {
        'exported': len(lean_product['package'].get('evidence', {}))
                    + len(lean_product['package'].get('excerpt_evidence', {})),
        'verified': bool(lean_verified) and all(lean_verified.values())}
    report['wsc_lean_matched']['usage'] = matched_extra['wsc_lean']
    report['wsc_lean_matched']['evidence'] = {
        'exported': len(lean_matched['package'].get('evidence', {}))
                    + len(lean_matched['package'].get('excerpt_evidence', {})),
        'verified': bool(lean_matched_verified) and all(lean_matched_verified.values())}
    report['wsc_thin']['usage'] = usage['wsc_thin']
    report['wsc_thin']['evidence'] = {'exported': len(thin2['evidence']),
                                      'verified': bool(thin1['verified'] and thin2['verified'])}
    report['wsc_thin_matched']['usage'] = matched_extra['wsc_thin']
    report['wsc_thin_matched']['evidence'] = {'exported': len(thin_matched['evidence']),
                                              'verified': bool(thin_matched['verified'])}
    wsc_files = {**product['package'].get('evidence', {}),
                 **product['package'].get('excerpt_evidence', {})}
    report['wsc']['evidence_scores'] = evidence_scores(
        case, 2, product['index'][2], archive_text(wsc_files))
    lean_files = {**lean_product['package'].get('evidence', {}),
                  **lean_product['package'].get('excerpt_evidence', {})}
    report['wsc_lean']['evidence_scores'] = evidence_scores(
        case, 2, lean_product['index'][2], archive_text(lean_files))
    report['wsc_thin']['evidence_scores'] = evidence_scores(
        case, 2, thin2['index'], archive_text(thin2['evidence']))
    gate = {'budget': budget, 'half_target': half, 'wsc_half_budget': product_budget,
            'wsc_half_bytes': product_bytes,
            'lean_half_budget': lean_budget, 'lean_half_bytes': lean_bytes,
            'matched_budget': matched_budget, 'matched_bytes': matched_bytes,
            'lean_matched_budget': lean_matched_budget, 'lean_matched_bytes': lean_matched_bytes,
            'thin_matched_budget': thin_matched_budget, 'thin_matched_bytes': thin_matched_bytes,
            'native_bytes': native2['bytes'],
            'ratio': {name: report[name]['ratio'][2] for name in materials},
            'compressed': all(report[name]['ratio'][2] <= MAX_RATIO for name in materials),
            'ratio_gap': round(abs(report['wsc_matched']['ratio'][2]
                                   - report['dsh_native']['ratio'][2]), 4),
            'lean_ratio_gap': round(abs(report['wsc_lean_matched']['ratio'][2]
                                        - report['dsh_native']['ratio'][2]), 4),
            'thin_ratio_gap': round(abs(report['wsc_thin_matched']['ratio'][2]
                                        - report['dsh_native']['ratio'][2]), 4)}
    gate['valid'] = bool(gate['compressed'] and report['wsc']['evidence']['exported']
                         and report['wsc']['evidence']['verified'])
    gate['lean_valid'] = bool(report['wsc_lean']['evidence']['exported']
                              and report['wsc_lean']['evidence']['verified'])
    gate['thin_valid'] = bool(report['wsc_thin']['evidence']['exported']
                              and report['wsc_thin']['evidence']['verified'])
    matched_gate = gate['ratio_gap'] <= 0.05
    lean_matched_gate = gate['lean_ratio_gap'] <= 0.05
    # The thin layer aims at or below the native checkpoint, not exactly equal:
    # extra bytes are never spent just to reach parity with a weaker arm.
    thin_matched_gate = thin_matched_bytes <= native2['bytes'] * 1.05
    gate['thin_ratio_delta'] = round(report['wsc_thin']['ratio'][2] - report['dsh_native']['ratio'][2], 4)
    result = {'case': case['case'], 'model': MODEL, 'gate': gate, 'matched_ratio': matched_gate,
              'lean_matched_ratio': lean_matched_gate,
              'thin_matched_ratio': thin_matched_gate,
              'arms': report,
              'wsc_sources': {'r1': work['chosen1'], 'r2': work['chosen2']},
              'lean_sources': {'r1': lean_work['chosen1'], 'r2': lean_work['chosen2']},
              'wsc_ledger': [entry.text for entry in work['entries1']],
              'lean_ledger': [entry.text for entry in lean_work['entries1']],
              'wsc_distilled_r2': work['distilled2'],
              'lean_distilled_r2': lean_work['distilled2'],
              'wsc_dropped': product['dropped'],
              'thin': {'entries': thin_work['entries'], 'state': thin_work['rounds'][2]['state'],
                       'audit': thin_work['audit'], 'repair': thin_work['repair'],
                       'receipts': thin_work['receipts'][2], 'raw2': thin_work['raw'][2],
                       'index': thin_work['rounds'][2]['index'],
                       'archive': len(thin_work['rounds'][2]['archive']), 'pruned': pruned},
              'retrieval': {'wsc': wsc_probe, 'wsc_lean': lean_probe, 'wsc_thin': thin_probe},
              'boundary': ('DSH arm uses the shipped COMPACTION_INSTRUCTION and 16% verbatim tail; '
                           'WSC asks one ledger-distillation call per compression and derives the '
                           'evidence from its cites; WSC-lean sends only the new round plus the ledger '
                           'after the first compression and uses one merged rule set; the thin arm asks '
                           'one bounded JSON call per round and the engine composes the natural-language '
                           'passage, binds verification and exports evidence; scoring is exact-needle '
                           'presence, not semantic judging; cost uses endpoint usage at cached 0.02 / '
                           'uncached 1.00 / output 4.00 yuan per million tokens')}
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'presented-native.txt').write_text(native2['presented'], encoding='utf-8')
    (root / 'presented-wsc.txt').write_text(product['presented'][2], encoding='utf-8')
    (root / 'presented-wsc-matched.txt').write_text(matched['presented'][2], encoding='utf-8')
    (root / 'presented-wsc-lean.txt').write_text(lean_product['presented'][2], encoding='utf-8')
    (root / 'presented-wsc-lean-matched.txt').write_text(lean_matched['presented'][2], encoding='utf-8')
    (root / 'presented-wsc-thin.txt').write_text(thin2['presented'], encoding='utf-8')
    (root / 'presented-wsc-thin-matched.txt').write_text(thin_matched['presented'], encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'benchmarks' / 'coding_compaction_v1' / 'runs')
    parser.add_argument('--case', action='append')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    out = args.out / time.strftime('%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    model = Model(load_key())
    selected = [factory() for factory in case_module.CASES]
    if args.case:
        selected = [case for case in selected if case['case'] in args.case]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [(case, pool.submit(measure_case, case, out, model)) for case in selected]
        for case, future in futures:
            results.append(future.result())
            result = results[-1]
            n = result['arms']['dsh_native']
            print(f"\n{case['case']}  model={MODEL}")
            print(f"  dsh_native ratio {n['ratio'][2]:.3f}  probe {n['scores'][2]['probe']:.2f}"
                  f"  constraints {n['scores'][2]['constraint_retention']:.2f}"
                  f"  recall {n['scores'][2]['key_recall']:.2f}"
                  f"  stale {len(n['scores'][2]['stale'])}"
                  f"  tokens {n['usage']['prompt_tokens']}/{n['usage']['completion_tokens']}"
                  f"  cost Y{n['usage']['cost']:.4f}")
            for name in ('wsc_thin_matched', 'wsc_thin', 'wsc_lean_matched', 'wsc_lean',
                         'wsc_matched', 'wsc'):
                w = result['arms'][name]
                print(f"  {name:<18} ratio {w['ratio'][2]:.3f}  probe {w['scores'][2]['probe']:.2f}"
                      f"  constraints {w['scores'][2]['constraint_retention']:.2f}"
                      f"  recall {w['scores'][2]['key_recall']:.2f}"
                      f"  stale {len(w['scores'][2]['stale'])}"
                      f"  tokens {w['usage']['prompt_tokens']}/{w['usage']['completion_tokens']}"
                      f"  cost Y{w['usage'].get('cost', 0.0):.4f}")
                if w.get('evidence_scores'):
                    e = w['evidence_scores']
                    print(f"    evidence discover {e['discover']:.2f}  retrieve {e['retrieve']:.2f}")
            print(f"  ratio gap {result['gate']['ratio_gap']:.3f}"
                  f"  wsc_text {result['gate']['matched_bytes']}B vs native {result['gate']['native_bytes']}B"
                  f"  matched {result['matched_ratio']}")
            print(f"  lean gap {result['gate']['lean_ratio_gap']:.3f}"
                  f"  lean_text {result['gate']['lean_matched_bytes']}B vs native"
                  f" {result['gate']['native_bytes']}B  matched {result['lean_matched_ratio']}")
            print(f"  thin delta {result['gate']['thin_ratio_delta']:+.3f}"
                  f"  thin_text {result['gate']['thin_matched_bytes']}B vs native"
                  f" {result['gate']['native_bytes']}B  at_or_below {result['thin_matched_ratio']}")
            rp = result['retrieval']
            print(f"  retrieval hit  wsc {rp['wsc'].get('hit_rate')}"
                  f"  lean {rp['wsc_lean'].get('hit_rate')}"
                  f"  thin {rp['wsc_thin'].get('hit_rate')}")
    summary = {'model': MODEL, 'results': results, 'calls': model.totals()}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'calls.jsonl').write_text(
        '\n'.join(json.dumps(call, ensure_ascii=False) for call in model.calls), encoding='utf-8')
    (out / 'responses.jsonl').write_text(
        '\n'.join(json.dumps(response, ensure_ascii=False) for response in model.responses), encoding='utf-8')
    print('\noutput', out)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
