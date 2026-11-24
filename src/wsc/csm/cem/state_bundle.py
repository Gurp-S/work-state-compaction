"""Publish current memory state as a first-class, structured prompt block.

The contract is deliberately not "a string of evidence".  A caller must receive
typed state items (clock, current fact, historical fact, pending binding, due
commitment, conflict) and, separately, the source evidence that supports them.
An empty state is explicit (``NO_CONFIRMED_STATE``); it is never silently
represented by a clock line alone.
"""
from __future__ import annotations

import json

from .commitment_projection import (PROPERTY_KEY, commitment_state_at, commitments_due,
                                    reviewed_commitment_candidates, reviewed_commitments_by_binding)
from .commitment_candidate_state import with_candidates
from ..contracts import CSMError
from .property_journal import _slot
from .visible_state import visible_state_rows


MAX_LINES = 24


def _turn_of(ref: str) -> int | None:
    """Map a source event id such as ``chat/101`` to its turn number."""
    if not isinstance(ref, str):
        return None
    head, _, tail = ref.rpartition('/')
    if head != 'chat' or not tail.isdigit():
        return None
    return int(tail)


def _value_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _item(kind: str, text: str, *, source_turns=(), **fields) -> dict:
    item = {'kind': kind, 'text': text,
            'source_turns': tuple(sorted(set(source_turns)))}
    item.update(fields)
    return item


def _scope_key(item):
    return str(item.get('entity')), str(item.get('slot')), tuple(item.get('contexts') or ())


def _label_with_scope(entity, slot, contexts):
    suffix = f"（范围：{'、'.join(contexts)}）" if contexts else ''
    return f'{entity} / {slot}{suffix}'


def _fact_item(item: dict) -> dict:
    entity = item.get('entity') or '?'
    slot = item.get('slot') or '?'
    contexts = tuple(item.get('contexts') or ())
    value = _value_text(item.get('value'))
    label = item.get('classification') or 'UNKNOWN'
    refs = [_turn_of(ref) for ref in item.get('source_refs') or ()]
    refs = [ref for ref in refs if ref is not None]
    provenance = f"；来源轮次 {','.join(map(str, refs))}" if refs else ''
    valid = item.get('valid_from') or item.get('effective_at')
    valid_text = f"；自 {valid}" if valid else ''
    text = f"[{label}] {_label_with_scope(entity, slot, contexts)} = {value}{valid_text}{provenance}"
    return _item(label, text, source_turns=refs, entity=entity, slot=slot, contexts=contexts,
                 value=item.get('value'), status=item.get('status'),
                 classification=label, revision=item.get('revision'))


def _conflict_items(results: list[dict]) -> list[dict]:
    """Two live values for one identity slot are a conflict, not two facts."""
    grouped = {}
    for item in results:
        grouped.setdefault(_scope_key(item), []).append(item)
    items = []
    for (entity, slot, contexts), group in grouped.items():
        values = {_value_text(item.get('value')) for item in group}
        if len(values) < 2:
            continue
        refs = sorted({ref for item in group for ref in (item.get('source_refs') or ())})
        turns = [turn for turn in (_turn_of(ref) for ref in refs) if turn is not None]
        provenance = f"；来源轮次 {','.join(map(str, turns))}" if turns else ''
        text = (f"[CONFLICT_UNRESOLVED] {_label_with_scope(entity, slot, contexts)} = "
                f"{' | '.join(sorted(values))}{provenance}")
        items.append(_item('CONFLICT_UNRESOLVED', text, source_turns=turns,
                           entity=entity, slot=slot, contexts=contexts, values=sorted(values)))
    return items


def _commitment_items(service, *, now: str, source_until: str, visible_source_ids,
                      binding_key=None, owner_ref=None, candidate_keys=()) -> list[dict]:
    scope = dict(now=now, source_until=source_until, visible_source_ids=visible_source_ids)
    try:
        if binding_key is not None:
            bound = commitment_state_at(service, **scope, binding_key=binding_key)
            rows = [bound] if bound else []
        elif owner_ref is not None:
            rows = reviewed_commitment_candidates(service, **scope, owner_ref=owner_ref)
        elif candidate_keys:
            rows = reviewed_commitments_by_binding(service, **scope, binding_keys=candidate_keys)
        else:
            rows = commitments_due(service, **scope, temporal_kind=None)
    except CSMError as error:
        if str(error) not in ('property_journal_not_initialized', 'entity_registry_not_initialized'):
            raise
        return []
    items = []
    for item in rows:
        commitment = item.get('commitment') or {}
        # Registry and property seals remain admission prerequisites. Only the
        # binding's own reviewed spans support the explicitly selected claim.
        source_refs = list(dict.fromkeys(span['event_id'] for span in item['evidence']))
        refs = [_turn_of(ref) for ref in source_refs]
        refs = [ref for ref in refs if ref is not None]
        provenance = f"；来源轮次 {','.join(map(str, refs))}" if refs else ''
        deadline = commitment.get('temporal_kind') == 'deadline'
        applicability = item.get('applicability', 'DEADLINE_DATE' if deadline else 'DUE')
        kind = applicability if applicability in ('DUE', 'DEADLINE_DATE') else 'COMMITMENT_STATE'
        text = (f"[{kind}] {item.get('owner_ref')} / {commitment.get('description')}；"
                + (f'{applicability}；' if kind == 'COMMITMENT_STATE' else '')
                + (f"原文截止日期 {commitment['due_start'][:10]}，是否包含当天未确认"
                   if deadline else f"{commitment['due_start']}..{commitment['due_end']}")
                + provenance)
        items.append(_item(kind, text, source_turns=refs,
                           owner_ref=item.get('owner_ref'),
                           binding_key=item['binding_key'], revision=item['revision'],
                           applicability=applicability,
                           commitment=commitment, source_spans=item['evidence']))
    if (owner_ref is not None or candidate_keys) and items:
        group = _item('PENDING_BINDING', '', owner_ref=owner_ref, reason='request_binding_required',
                      candidate_count=len(items))
        if candidate_keys:
            group['coverage'] = 'reviewed_candidates_only'
        return [with_candidates(group, items)]
    return items


def render_state_items(items: list[dict]) -> str:
    lines = []
    for item in items:
        if item.get('kind') == 'CLOCK':
            lines.append(f"【当前时间】{item['now']}")
        else:
            lines.append(item.get('text') or f"[{item.get('kind')}]")
    return '\n'.join(['【状态】', *lines])


def build_state_bundle(service, *, now: str, source_until: str, visible_source_ids,
                       question: str, max_chars: int = 1200, revision_state=False,
                       commitment_binding=None, commitment_owner=None,
                       include_unbound_commitments=True, commitment_candidates=()) -> dict:
    """Build typed state items plus their rendered prompt block.

    Returns ``{"items": [...], "text": str, "turns": tuple[int, ...]}``.
    ``items`` is the contract; ``text`` is only its rendering.
    A supplied ``commitment_binding`` limits the bundle to that reviewed event,
    including its applicability outside the named date.
    A supplied ``commitment_owner`` keeps visible candidates pending request binding.
    """
    if sum((commitment_binding is not None, commitment_owner is not None, bool(commitment_candidates))) > 1:
        raise ValueError('commitment_scope_ambiguous')
    scoped_commitment = commitment_binding is not None or commitment_owner is not None
    items: list[dict] = [_item('CLOCK', f"【当前时间】{now}", now=now)]
    turns: set[int] = set()
    visible = frozenset(visible_source_ids)

    if scoped_commitment:
        results = []
    elif revision_state:
        with service.store.connect() as db:
            results = visible_state_rows(db, question, source_until=source_until, visible_source_ids=visible)
    else:
        try:
            found = service.search(question, limit=12, window=(None, source_until))
            results = [item for item in found.get('results') or []
                       if item.get('source_refs') and set(item['source_refs']) <= visible]
        except CSMError:
            results = []

    if not include_unbound_commitments:
        # The generic property projection contains the same journal-backed rows.
        # Publish commitments solely via their time- and request-scoped projection.
        results = [item for item in results if item.get('slot') != _slot(PROPERTY_KEY)]
    current = [item for item in results if item.get('classification') == 'CURRENT_CONFIRMED']
    historical = [item for item in results if item.get('classification') == 'HISTORICAL']
    pending = [item for item in results if item.get('classification') == 'PENDING_BINDING']

    due = []
    if scoped_commitment or include_unbound_commitments or commitment_candidates:
        due = _commitment_items(service, now=now, source_until=source_until, visible_source_ids=visible,
                                binding_key=commitment_binding, owner_ref=commitment_owner,
                                candidate_keys=commitment_candidates)
    conflicts = _conflict_items(current)
    conflicting = {_scope_key(item) for item in conflicts}
    active = [item for item in current if _scope_key(item) not in conflicting][:8]
    pairs = {item['memory_id']: item for item in historical if item.get('superseded_by') is not None}
    groups = [[item] for item in due + conflicts]
    for item in active:
        earlier = pairs.get(item.get('memory_id'))
        groups.append([_fact_item(item), _fact_item(earlier)] if earlier else [_fact_item(item)])
    groups += [[_fact_item(item)] for item in historical[:4] if item.get('superseded_by') is None]
    groups += [[_fact_item(item)] for item in pending[:4]]

    for group in groups:
        if len(group) == 1 and 'candidate_count' in group[0]:
            pending_group = group[0]
            retained = []
            for candidate in pending_group['candidates']:
                proposed = with_candidates(pending_group, [*retained, candidate])
                if len(render_state_items(items + [proposed])) <= max_chars:
                    retained.append(candidate)
            group = [with_candidates(pending_group, retained)] if retained else []
        if len(render_state_items(items + group)) > max_chars and len(group) == 2:
            primary = {**group[0], 'history_omitted': 'state_budget'}
            marked = {**primary, 'text': primary['text'] + '；旧版本因预算省略'}
            group = [marked if len(render_state_items(items + [marked])) <= max_chars else primary]
        if len(render_state_items(items + group)) > max_chars:
            continue
        items.extend(group)
        for item in group:
            turns.update(item.get('source_turns') or ())

    if len(items) == 1:
        items.append(_item('NO_CONFIRMED_STATE',
                           '[NO_CONFIRMED_STATE] 没有可交付的已确认记忆状态。',
                           reason=('state_budget' if groups else 'binding_not_visible'
                                   if scoped_commitment else 'no_memory_rows')))
    bundle = {'items': items, 'text': render_state_items(items), 'turns': tuple(sorted(turns))}
    if commitment_candidates and due:
        bundle['pending_commitment_spans'] = due[0]['source_spans']
    return bundle
