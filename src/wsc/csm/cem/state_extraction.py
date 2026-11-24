"""State producer interface for CSM retrieval.

The engine owns the contract; a producer may be a model, a deterministic rule or
a test fixture.  The important part is that retrieval cannot fall back to
"evidence only": a producer must either return typed state items or explicitly
return an empty list, which the adapter renders as NO_CONFIRMED_STATE.
"""
from __future__ import annotations

import json

from .calendar_anchors import resolve_source_calendar_day, resolve_source_deadline_date
from .calendar_windows import resolve_source_calendar_window
from .commitment_candidates import discover_commitment_candidates
from ..contracts import parse_instant
from .state_bundle import render_state_items


class StateProducerResponseError(ValueError):
    """The producer returned a response that cannot supply typed state."""


STATE_SYSTEM = """You are a state compiler, not a summarizer.
Input: the current time, a question, and the visible source excerpts.
Return only JSON: {"items": [ ... ]}.
Each item must have:
  kind: CURRENT_CONFIRMED | HISTORICAL | PENDING_BINDING | SCHEDULED | DEADLINE | CONFLICT_UNRESOLVED | UNKNOWN
  entity: string (use "用户" for the user)
  slot: string
  value: string
  source_turns: [integer turn numbers]
  citations: [{"turn": integer, "field": "user" or "assistant", "quote": "exact source substring"}]
For SCHEDULED: date_anchor: {"turn": integer, "field": "user", "quote": "exact single-day expression"}.
For DEADLINE: the same date_anchor includes the original deadline qualifier, for example "by next Friday".
Rules:
- Only state what the excerpts support. Do not infer from the question.
- At most four items directly relevant to the current request. Unrelated true facts are outside the result.
- A later correction replaces an earlier value; do not emit both as CURRENT.
- Two conflicting values with no supersession are CONFLICT_UNRESOLVED, not two facts.
- SCHEDULED describes a source-backed event or commitment with a definite single day and no unresolved activation condition.
  Candidate date_mentions are parsed expressions; the engine compares the selected date to the clock.
- An assistant restatement cannot establish a current value or scheduled event on its own.
- If the excerpts contain no usable state, return {"items": []}."""


def _item(raw: dict, now: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get('kind') or '').strip()
    if kind not in ('CURRENT_CONFIRMED', 'HISTORICAL', 'PENDING_BINDING', 'DUE', 'SCHEDULED', 'DEADLINE',
                    'CONFLICT_UNRESOLVED', 'UNKNOWN'):
        return None
    entity = str(raw.get('entity') or '').strip()
    slot = str(raw.get('slot') or '').strip()
    value = raw.get('value')
    if not entity or not slot or not isinstance(value, str) or not value.strip():
        return None
    refs = raw.get('source_turns')
    if not isinstance(refs, list) or not refs or any(type(turn) is not int or turn < 1 for turn in refs):
        return None
    refs = tuple(dict.fromkeys(refs))
    text = f"[{kind}] {entity} / {slot} = {value}"
    if refs:
        text += f"；来源轮次 {','.join(map(str, refs))}"
    return {'kind': kind, 'text': text, 'source_turns': refs,
            'entity': entity, 'slot': slot, 'value': value,
            'status': 'source_projection', 'now': now}


def _source_quote(raw, sources):
    if not isinstance(raw, dict) or type(raw.get('turn')) is not int:
        return None
    field, quote = raw.get('field'), raw.get('quote')
    source = sources.get(raw['turn'])
    if (source is None or field not in ('user', 'assistant') or not isinstance(quote, str)
            or not quote.strip() or quote not in source[field]):
        return None
    return source


def parse_state_items(payload, now: str, *, sources=None, retain_off_day=False) -> list[dict]:
    """Parse a producer response into typed items; malformed items are dropped."""
    raw_items = payload.get('items') if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw in raw_items[:12]:
        item = _item(raw, now)
        if item is None:
            continue
        if sources is not None:
            citations = raw.get('citations')
            if (not isinstance(citations, list) or not citations
                    or any(_source_quote(cite, sources) is None for cite in citations)
                    or {cite['turn'] for cite in citations} != set(item['source_turns'])):
                continue
            # A source-backed unknown describes uncertainty in the user's record.
            # The producer's inability to establish a value is represented by the
            # bundle's NO_CONFIRMED_STATE, without a fabricated source attribution.
            if (item['kind'] in ('CURRENT_CONFIRMED', 'UNKNOWN')
                    and not any(cite['field'] == 'user' for cite in citations)):
                continue
            if item['kind'] in ('DUE', 'SCHEDULED', 'DEADLINE'):
                anchor = raw.get('date_anchor')
                source = _source_quote(anchor, sources)
                if source is None or anchor['turn'] not in item['source_turns'] or anchor['field'] != 'user':
                    continue
                original = source.get('_full', source)
                deadline = item['kind'] == 'DEADLINE'
                resolve = resolve_source_deadline_date if deadline else resolve_source_calendar_day
                day = resolve(anchor['quote'], original[anchor['field']], source['time'])
                window = day is None and resolve_source_calendar_window(anchor['quote'], original[anchor['field']],
                                                                        source['time'])
                if window:
                    day = window
                if day is None:
                    continue
                clock = parse_instant(now)
                on_date = parse_instant(day[0]) <= clock < parse_instant(day[1])
                if not on_date and not retain_off_day:
                    continue
                if not any(cite['turn'] == anchor['turn'] and cite['field'] == anchor['field']
                           and anchor['quote'] in cite['quote'] for cite in citations):
                    citations = [*citations, {field: anchor[field] for field in ('turn', 'field', 'quote')}]
                item.update(due_start=day[0], due_end=day[1])
                kind = 'TEMPORAL_WINDOW' if window else (
                    ('DEADLINE_DATE' if deadline else 'DUE') if on_date else 'COMMITMENT_STATE')
                item['text'] = item['text'].replace(f"[{item['kind']}]", f'[{kind}]', 1)
                item['kind'] = kind
                if window:
                    applicability = ('WITHIN_SOURCE_WINDOW' if on_date else 'BEFORE_SOURCE_WINDOW'
                                     if clock < parse_instant(day[0]) else 'AFTER_SOURCE_WINDOW')
                    item['applicability'] = applicability
                    item['text'] += (f'；原文时段 {day[0]}..{day[1]}（终点不含）；{applicability}'
                                     f'；用户原话：{anchor["quote"]}')
                elif not on_date:
                    applicability = 'BEFORE_NAMED_DATE' if clock < parse_instant(day[0]) else 'AFTER_NAMED_DATE'
                    item['applicability'] = applicability
                    refs = ','.join(map(str, item['source_turns']))
                    date = day[0][:10]
                    label = '原文截止日期' if deadline else '原文日期'
                    item['text'] = (f"[{kind}] {item['entity']} / {item['slot']}；{label} {date}；"
                                    f'{applicability}；事项完成状态未确认；来源轮次 {refs}')
                    if deadline:
                        item['text'] += '；是否包含当天未确认'
                    quotes = dict.fromkeys(cite['quote'] for cite in citations
                                           if cite['field'] == 'user' and len(cite['quote']) <= 160)
                    if quotes:
                        item['text'] += '；用户原话：' + ' / '.join(list(quotes)[:2])
                elif deadline:
                    item['text'] += f'；原文截止日期 {day[0][:10]}，是否包含当天未确认'
                else:
                    item['text'] += f'；{day[0]}..{day[1]}'
            item['citations'] = citations
        items.append(item)
    return items


class ModelStateExtractor:
    """Read-time state compiler backed by a JSON chat callable."""

    def __init__(self, ask_json, *, retain_off_day=False):
        self.ask_json = ask_json
        self.retain_off_day = retain_off_day

    def extract(self, question: str, evidence: dict, now: str) -> list[dict]:
        if not evidence:
            return []
        visible = []
        clock = parse_instant(now)
        for source in evidence.values():
            row = {key: source[key] for key in ('turn', 'time', 'user', 'assistant')}
            original = source.get('_full', source)
            date_mentions = []
            for candidate in discover_commitment_candidates(
                f'chat/{row["turn"]}', 'user', original['user'], row['time']
            ):
                if (candidate.day and candidate.text in row['user']
                        and parse_instant(candidate.day[0]) <= clock < parse_instant(candidate.day[1])):
                    date_mentions.append({'quote': candidate.text, 'day': candidate.day[0][:10],
                                          'kind': candidate.kind})
            if date_mentions:
                row['date_mentions'] = date_mentions
            visible.append(row)
        user = json.dumps({'now': now, 'question': question, 'evidence': visible},
                          ensure_ascii=False)
        payload = self.ask_json(STATE_SYSTEM, user, max_tokens=900)
        if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
            raise StateProducerResponseError('state_producer_invalid_response')
        return parse_state_items(payload, now, sources=evidence, retain_off_day=self.retain_off_day)


def merge_state_items(bundle_items: list[dict], produced: list[dict]) -> list[dict]:
    """Keep the clock first; replace the explicit empty marker when state exists."""
    produced = [item for item in produced if item.get('kind') != 'NO_CONFIRMED_STATE']
    if not produced:
        return list(bundle_items)
    kept = [item for item in bundle_items if item.get('kind') != 'NO_CONFIRMED_STATE']
    return kept + produced


def render_items(items: list[dict]) -> str:
    return render_state_items(items)
