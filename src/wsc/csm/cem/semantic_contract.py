"""Read-only planning of caller-declared property and membership semantics.

This module validates structure and literal provenance. It never decides whether
a quotation entails a relation, commits state, or infers a complete collection.
Existing explicit_write remains the sole value-operation implementation.
"""
from dataclasses import asdict, dataclass
import json

from ..contracts import digest
from . import domain, identity, state
from ..contracts import (MemoryCandidate, ORGANIZATION_RELATIONS, anchors, parse_instant,
                        require, validate_candidate, validate_instant)
from .explicit_write import OPERATIONS, _set

POLICY = 'declared-property-contract-v1'


@dataclass(frozen=True)
class SourceSpan:
    event_id: str
    path: tuple  # Exact JSON path, e.g. ('turns', 2, 'text').
    quote: str


@dataclass(frozen=True)
class PropertySpec:
    key: str  # Stable caller registry key; never extracted from a free-text slot.
    cardinality: str  # single, set, observation
    relation_kind: str | None = None
    owner_role: str | None = None  # subject or object in membership relation


@dataclass(frozen=True)
class PropertyBinding:
    owner_ref: str  # Registered entity ID, or node in the older read-only prototype.
    contexts: tuple[str, ...] = ()
    memory_id: str | None = None
    expected_revision: int | None = None
    expected_value: object = None
    evidence: tuple[SourceSpan, ...] = ()


@dataclass(frozen=True)
class RelationClaim:
    kind: str
    subject: str
    object: str
    effect: str  # assert, end; ending is not a claim that it never existed.
    evidence: tuple[SourceSpan, ...]
    contexts: tuple[str, ...] = ()


def _entity(db, ref, *, registry=False, cutoff=None):
    if registry:
        from .entity_registry import require_entity
        return require_entity(db, ref, cutoff=cutoff)
    require(isinstance(ref, str) and ref.startswith('node:') and len(ref) > 5,
            'property_entity_ref_invalid')
    row = db.execute('SELECT node_type,status FROM tree_nodes WHERE node_id=?', (ref[5:],)).fetchone()
    require(row is not None, 'property_entity_ref_unknown')
    require(row['node_type'] == 'entity' and row['status'] == 'active',
            'property_entity_ref_unavailable')


def _spans(db, spans, cutoff):
    require(isinstance(spans, (list, tuple)), 'property_spans_invalid')
    out = []
    for span in spans:
        require(isinstance(span, SourceSpan), 'property_span_invalid')
        require(isinstance(span.event_id, str) and bool(span.event_id), 'property_span_event_invalid')
        require(isinstance(span.path, tuple) and bool(span.path), 'property_span_path_invalid')
        require(isinstance(span.quote, str) and bool(span.quote.strip()), 'property_span_quote_missing')
        event = db.execute('SELECT data,digest,observed_at FROM events WHERE id=?', (span.event_id,)).fetchone()
        require(event is not None, 'evidence_source_unknown')
        value = json.loads(event['data'])
        require(digest(value) == event['digest'], 'evidence_source_digest_mismatch')
        if cutoff:
            require(bool(event['observed_at']) and parse_instant(event['observed_at']) <= cutoff,
                    'property_source_outside_cutoff')
        for part in span.path:
            if isinstance(value, dict) and isinstance(part, str) and part in value:
                value = value[part]
            elif isinstance(value, list) and type(part) is int and 0 <= part < len(value):
                value = value[part]
            else:
                require(False, 'property_span_path_missing')
        require(isinstance(value, str) and span.quote in value, 'property_span_quote_mismatch')
        out.append(asdict(span))
    return out


def validate_spec(spec):
    require(isinstance(spec, PropertySpec), 'property_contract_invalid')
    require(isinstance(spec.key, str) and bool(spec.key.strip()), 'property_key_missing')
    require(spec.cardinality in ('single', 'set', 'observation'), 'property_cardinality_invalid')
    if spec.cardinality == 'set':
        require(spec.relation_kind in ORGANIZATION_RELATIONS and spec.owner_role in ('subject', 'object'),
                'property_membership_schema_missing')
    else:
        require(spec.relation_kind is None and spec.owner_role is None, 'property_membership_schema_unexpected')


def plan(service, spec: PropertySpec, binding: PropertyBinding, candidate: MemoryCandidate, *,
         operation=None, relations=(), coverage='partial', coverage_evidence=(), until=None,
         entity_ids=False):
    """Return an uncommitted review plan; missing declarations remain pending_review.

    All registry/endpoint/attribution/operation choices come from the caller. A
    structurally valid plan is still semantically unverified, including complete
    snapshot claims. Nothing here is automatically applied to explicit_write or
    the legacy relation graph.
    """
    require(isinstance(spec, PropertySpec) and isinstance(binding, PropertyBinding), 'property_contract_invalid')
    require(type(entity_ids) is bool, 'property_entity_mode_invalid')
    validate_spec(spec)
    require(operation is None or operation in OPERATIONS, 'value_operation_unknown')
    require(coverage in ('partial', 'source_claimed_complete'), 'property_coverage_invalid')
    require(not coverage_evidence or coverage == 'source_claimed_complete', 'property_coverage_evidence_unexpected')
    data = validate_candidate(candidate)
    domain.validate_status(data['semantic_type'], data['status'])
    require(data['intent'] == 'auto' and data['target_memory_id'] is None,
            'explicit_write_candidate_intent_conflict')
    contexts = anchors(binding.contexts, field='context')
    cutoff = parse_instant(validate_instant(until, field='until')) if until else None
    missing = []
    if operation is None:
        missing.append('value_operation')
    with service.store.connect() as db:
        def check_entity(ref):
            return _entity(db, ref, registry=entity_ids, cutoff=cutoff)
        check_entity(binding.owner_ref)
        evidence = _spans(db, binding.evidence, cutoff)
        complete_evidence = _spans(db, coverage_evidence, cutoff)
        require(isinstance(relations, (list, tuple)), 'property_relations_invalid')
        checked = []
        for relation in relations:
            require(isinstance(relation, RelationClaim), 'property_relation_invalid')
            require(spec.cardinality == 'set' and relation.kind == spec.relation_kind,
                    'property_relation_kind_mismatch')
            require(relation.effect in ('assert', 'end'), 'property_relation_effect_invalid')
            require(relation.subject != relation.object, 'relation_self')
            check_entity(relation.subject); check_entity(relation.object)
            require(anchors(relation.contexts, field='context') == contexts, 'property_relation_context_mismatch')
            require(bool(relation.evidence), 'relation_evidence_missing')
            spans = _spans(db, relation.evidence, cutoff)
            checked.append({**asdict(relation), 'evidence': spans})
        previous = None
        if binding.memory_id is not None:
            require(isinstance(binding.memory_id, str) and bool(binding.memory_id), 'target_memory_id_invalid')
            # A binding names an exact identity, not a moving merge redirect.
            owner = identity.identity_row(db, binding.memory_id)
            require(not owner.get('merged_into'), 'property_target_merged')
            require(anchors(owner['contexts'], field='context') == contexts, 'property_target_context_mismatch')
            previous = state.head(db, binding.memory_id)
            require(previous is not None, 'memory_revision_missing')
            require(binding.expected_revision is None or type(binding.expected_revision) is int,
                    'expected_revision_invalid')
            require(binding.expected_revision == data['expected_revision'], 'property_revision_declarations_mismatch')
            state.validate_transition(previous, data)
            require(digest(previous['value']) == digest(binding.expected_value), 'property_base_value_mismatch')
            if binding.expected_revision is None:
                missing.append('expected_revision')
        else:
            require(binding.expected_revision is None and binding.expected_value is None,
                    'property_base_without_target')
        if not evidence:
            missing.append('owner_property_binding_evidence')
        if operation == 'observe':
            require(binding.memory_id is None and data['expected_revision'] is None,
                    'observation_state_target_present')
            require(coverage == 'partial', 'observation_complete_state_claim')
        else:
            require(spec.cardinality != 'observation', 'property_observation_state_operation')
            require(tuple(data['contexts']) == contexts or binding.memory_id is not None,
                    'property_create_context_mismatch')
            if operation == 'create':
                require(binding.memory_id is None and data['expected_revision'] is None,
                        'create_identity_binding_present')
            elif operation is not None and binding.memory_id is None:
                missing.append('target_memory_id')
            if spec.cardinality == 'single':
                require(operation not in ('set_add', 'set_remove'), 'property_single_delta_invalid')
                require(not checked and coverage == 'partial', 'property_single_collection_claim')
            else:
                require(data['semantic_type'] == 'Fact' and data['lifecycle'] == 'open'
                        and (previous is None or (previous['semantic_type'] == 'Fact'
                             and previous['lifecycle'] == 'open')), 'collection_state_scope')
                _set(data['value'])
                for member in data['value']:
                    check_entity(member)
                if previous:
                    _set(previous['value'])
                    for member in previous['value']:
                        check_entity(member)
                effect = 'end' if operation == 'set_remove' else 'assert'
                expected_pairs = {(binding.owner_ref, member) if spec.owner_role == 'subject'
                                  else (member, binding.owner_ref) for member in data['value']}
                actual_pairs = {(r['subject'], r['object']) for r in checked if r['effect'] == effect}
                require(len(checked) == len(actual_pairs), 'property_relation_duplicate_or_effect_mismatch')
                require(actual_pairs <= expected_pairs, 'property_relation_member_mismatch')
                if actual_pairs != expected_pairs:
                    missing.append('member_relation_evidence')
                if operation == 'replace' and coverage != 'source_claimed_complete':
                    missing.append('replacement_complete_snapshot_declaration')
                if coverage == 'source_claimed_complete':
                    require(operation in ('create', 'replace'), 'property_delta_complete_claim')
                    if not complete_evidence:
                        missing.append('complete_snapshot_evidence')
            if not data['valid_from']:
                missing.append('effective_time')
            elif previous:
                require(parse_instant(data['valid_from']) >= parse_instant(previous['valid_from']),
                        'property_historical_change_requires_review')
            if data['valid_from'] and cutoff:
                require(parse_instant(data['valid_from']) <= cutoff, 'property_effective_after_cutoff')
        # Even source IDs not quoted by a role must exist and pass integrity/cutoff.
        source_ids = list(dict.fromkeys([*data['source_ids'],
            *((previous or {}).get('source_refs', [])),
            *(s['event_id'] for s in evidence + complete_evidence),
            *(s['event_id'] for r in checked for s in r['evidence'])]))
        for source_id in source_ids:
            event = db.execute('SELECT data,digest,observed_at FROM events WHERE id=?', (source_id,)).fetchone()
            require(event is not None, 'evidence_source_unknown')
            require(digest(json.loads(event['data'])) == event['digest'], 'evidence_source_digest_mismatch')
            if cutoff:
                require(bool(event['observed_at']) and parse_instant(event['observed_at']) <= cutoff,
                        'property_source_outside_cutoff')
    return {'policy': 'declared-entity-property-v2' if entity_ids else POLICY,
        **({'entity_identity': 'independent_registry'} if entity_ids else {}),
        'status': 'pending_review' if missing else 'structurally_valid',
        'missing_conditions': missing, 'property': asdict(spec), 'binding': asdict(binding),
        'property_schema_digest': digest(asdict(spec)),
        'candidate': asdict(candidate), 'operation': operation, 'relations': checked,
        'coverage': coverage, 'coverage_evidence': complete_evidence, 'source_refs': source_ids,
        'binding_key': digest({'owner': binding.owner_ref, 'property': spec.key, 'contexts': contexts}),
        'source_validation': 'digest_and_literal_spans_checked', 'attribution': 'caller_declared',
        'semantic_support': 'not_verified', 'classification': 'UNKNOWN', 'confirmed': False,
        'world_total': None, 'completeness': 'not_established', 'state_changed': False,
        'requires_semantic_review': True}
