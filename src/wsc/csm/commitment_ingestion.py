"""Stage literal-source commitment drafts for the existing reviewed journal."""
from dataclasses import dataclass
import json

from .calendar_anchors import resolve_source_calendar_day, resolve_source_deadline_date
from .commitment_projection import PROPERTY_KEY, validate_commitment
from .contracts import MemoryCandidate, parse_instant, require, validate_instant
from .property_journal import PropertyJournal
from .semantic_contract import PropertyBinding, SourceSpan, _spans


@dataclass(frozen=True)
class CommitmentDraft:
    source: SourceSpan
    owner_ref: str
    context: str
    description: str
    status: str
    condition: str
    date_expression: str | None
    target_binding: str | None = None
    expected_revision: int | None = None
    date_source: SourceSpan | None = None
    supporting_sources: tuple[SourceSpan, ...] = ()
    temporal_kind: str | None = None


def stage_commitment(service, draft: CommitmentDraft, *, request_id: str, source_until: str):
    """Return a journal proposal or an unresolved temporal anchor.

    The caller supplies the relation between the event, its owner and the
    quoted date. Only the journal's separate review and commit publish state.
    """
    cutoff_text = validate_instant(source_until, field='source_until')
    require(cutoff_text is not None, 'commitment_cutoff_missing')
    cutoff = parse_instant(cutoff_text)
    require(draft.date_source is None or draft.date_expression is not None, 'commitment_date_expression_missing')
    date_source = draft.date_source or draft.source
    require(isinstance(draft.supporting_sources, tuple), 'property_spans_invalid')
    with service.store.connect() as db:
        spans = (draft.source, date_source, *draft.supporting_sources)
        _spans(db, spans, cutoff)
        spans = tuple(dict.fromkeys(spans))
        refs = tuple(dict.fromkeys(span.event_id for span in spans))
        rows = {ref: db.execute('SELECT observed_at,data FROM events WHERE id=?', (ref,)).fetchone()
                for ref in refs}
        observed = max((row['observed_at'] for row in rows.values()), key=parse_instant)
        date_row = rows[date_source.event_id]
        source_field = json.loads(date_row['data'])
        for key in date_source.path:
            source_field = source_field[key]

    journal = PropertyJournal(service)
    previous = None
    if draft.target_binding is not None:
        state = journal.inspect(draft.target_binding)
        binding = state['binding']
        previous = state['head']
        require(binding['property_key'] == PROPERTY_KEY and binding['owner_ref'] == draft.owner_ref
                and tuple(binding['contexts']) == (draft.context,), 'commitment_binding_mismatch')
        require(type(draft.expected_revision) is int and previous['revision'] == draft.expected_revision,
                'commitment_revision_conflict')
    else:
        require(draft.expected_revision is None and draft.status == 'scheduled', 'commitment_initial_operation_invalid')

    inherited_kind = previous['value'].get('temporal_kind', 'appointment') if previous else 'appointment'
    temporal_kind = inherited_kind if draft.temporal_kind is None else draft.temporal_kind
    require(temporal_kind in ('appointment', 'deadline'), 'commitment_temporal_kind_invalid')
    if draft.date_expression is None:
        require(temporal_kind == inherited_kind, 'commitment_temporal_change_without_date')
        window = ((previous['value']['due_start'], previous['value']['due_end']) if previous else None)
        date_evidence = previous['value'].get('date_evidence') if previous else None
        if date_evidence is not None:
            validate_commitment(previous['value'])
            inherited = SourceSpan(date_evidence['event_id'], tuple(date_evidence['path']), date_evidence['quote'])
            with service.store.connect() as db:
                _spans(db, (inherited,), cutoff)
            spans = tuple(dict.fromkeys((*spans, inherited)))
            refs = tuple(dict.fromkeys(span.event_id for span in spans))
    else:
        require(isinstance(draft.date_expression, str) and bool(draft.date_expression.strip())
                and draft.date_expression in date_source.quote, 'commitment_date_not_in_source')
        resolve = resolve_source_deadline_date if temporal_kind == 'deadline' else resolve_source_calendar_day
        window = resolve(draft.date_expression, source_field, date_row['observed_at'])
        date_evidence = {'event_id': date_source.event_id, 'path': list(date_source.path), 'quote': date_source.quote}
    if window is None:
        return {'status': 'pending_date', 'source': draft.source.event_id}

    start, end = window
    value = {'description': draft.description, 'status': draft.status, 'condition': draft.condition,
             'due_start': start, 'due_end': end}
    if temporal_kind == 'deadline':
        value['temporal_kind'] = temporal_kind
    if date_evidence is not None:
        value['date_evidence'] = date_evidence
    validate_commitment(value)
    contexts = (draft.context,)
    binding = PropertyBinding(draft.owner_ref, contexts=contexts,
                              memory_id=previous['memory_id'] if previous else None,
                              expected_revision=draft.expected_revision,
                              expected_value=previous['value'] if previous else None,
                              evidence=spans)
    candidate = MemoryCandidate(draft.owner_ref, PROPERTY_KEY, value, contexts=contexts,
                                source_ids=refs, valid_from=observed,
                                expected_revision=draft.expected_revision)
    return journal.propose(request_id=request_id, spec_key=PROPERTY_KEY, binding=binding, candidate=candidate,
                           operation='replace' if previous else 'create', until=source_until)
