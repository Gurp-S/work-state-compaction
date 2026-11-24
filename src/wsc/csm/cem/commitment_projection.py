"""Query reviewed commitment revisions against a clock and a source cutoff."""
import json

from ..contracts import digest
from ..contracts import parse_instant, require, validate_instant
from .entity_registry import _ready as require_entity_registry, _verify as verify_entity_evidence
from .property_journal import _proposal, _ready, _snapshot, _verify_seals


PROPERTY_KEY = 'csm:commitment/v1'


def _instant(value, field):
    require(isinstance(value, str) and bool(value), 'commitment_time_missing')
    return parse_instant(validate_instant(value, field=field))


def validate_commitment(value):
    fields = {'description', 'status', 'condition', 'due_start', 'due_end'}
    require(isinstance(value, dict) and fields <= value.keys() <= fields | {'temporal_kind', 'date_evidence'},
            'commitment_value_invalid')
    if 'date_evidence' in value:
        source = value['date_evidence']
        require(isinstance(source, dict) and source.keys() == {'event_id', 'path', 'quote'}
                and isinstance(source['event_id'], str) and bool(source['event_id'])
                and isinstance(source['path'], list) and bool(source['path'])
                and isinstance(source['quote'], str) and bool(source['quote'].strip()),
                'commitment_date_evidence_invalid')
    require(value.get('temporal_kind', 'appointment') in ('appointment', 'deadline'),
            'commitment_temporal_kind_invalid')
    require(isinstance(value['description'], str) and bool(value['description'].strip()),
            'commitment_description_missing')
    require(value['status'] in ('scheduled', 'cancelled', 'fulfilled'), 'commitment_status_invalid')
    require(value['condition'] in ('unconditional', 'satisfied', 'unknown', 'unsatisfied'),
            'commitment_condition_invalid')
    start = _instant(value['due_start'], 'due_start')
    end = _instant(value['due_end'], 'due_end')
    require(start < end, 'commitment_interval_invalid')
    return start, end


def commitments_due(service, *, now, source_until, owner_ref=None, visible_source_ids=None,
                    temporal_kind='appointment'):
    """Return due reviewed claims visible by source time, with literal provenance.

    Source time restricts admissible evidence. The evaluation clock determines
    applicability. Each binding identifies one commitment through its revisions.
    Deadline queries match the named date and make no claim about inclusivity.
    """
    return _project(service, now=now, source_until=source_until, owner_ref=owner_ref,
                    visible_source_ids=visible_source_ids, temporal_kind=temporal_kind)


def commitment_state_at(service, *, binding_key, now, source_until, visible_source_ids=None):
    """Return the applicable reviewed revision for an explicitly bound event."""
    require(isinstance(binding_key, str) and bool(binding_key.strip()), 'commitment_binding_required')
    rows = _project(service, now=now, source_until=source_until, visible_source_ids=visible_source_ids,
                    temporal_kind=None, binding_key=binding_key)
    return rows[0] if rows else None


def reviewed_commitment_candidates(service, *, owner_ref, now, source_until, visible_source_ids):
    """List visible reviewed candidates for an already resolved owner.

    The caller still needs to bind the request to a candidate. An event being
    due gives it no priority over an independent event for the same owner.
    """
    require(isinstance(owner_ref, str) and bool(owner_ref.strip()), 'commitment_owner_required')
    return _project(service, now=now, source_until=source_until, owner_ref=owner_ref,
                    visible_source_ids=visible_source_ids, temporal_kind=None, include_applicability=True)


def reviewed_commitments_by_binding(service, *, binding_keys, now, source_until, visible_source_ids):
    """Revalidate a candidate set within one read transaction and one source cutoff."""
    keys = frozenset(binding_keys)
    require(all(isinstance(key, str) and key.strip() for key in keys), 'commitment_binding_required')
    if not keys:
        return []
    return _project(service, now=now, source_until=source_until, visible_source_ids=visible_source_ids,
                    temporal_kind=None, include_applicability=True, binding_keys=keys)


def reviewed_commitments_from_sources(service, *, source_refs, now, source_until, visible_source_ids):
    """Resolve reviewed source links to visible current revisions of the same commitments."""
    require(isinstance(source_refs, (tuple, list, set, frozenset))
            and all(isinstance(ref, str) and ref for ref in source_refs), 'commitment_source_refs_invalid')
    if not source_refs:
        return []
    return _project(service, now=now, source_until=source_until, visible_source_ids=visible_source_ids,
                    temporal_kind=None, include_applicability=True, source_refs=frozenset(source_refs))


def _applicability(value, clock, start, end):
    if value['status'] != 'scheduled':
        return value['status'].upper()
    if value['condition'] == 'unknown':
        return 'CONDITION_UNRESOLVED'
    if value['condition'] == 'unsatisfied':
        return 'CONDITION_UNSATISFIED'
    if clock < start:
        return 'BEFORE_NAMED_DATE'
    if clock >= end:
        return 'AFTER_NAMED_DATE'
    return 'DEADLINE_DATE' if value.get('temporal_kind') == 'deadline' else 'DUE'


def reviewed_commitments_from_mentions(service, *, text, now, source_until, visible_source_ids):
    """Use visible literal owner labels as candidate anchors, without resolving identity."""
    return _project(service, now=now, source_until=source_until, visible_source_ids=visible_source_ids,
                    temporal_kind=None, include_applicability=True, mention_text=text)


def _mentioned_owners(db, text, *, cutoff, visible):
    require_entity_registry(db)
    owners = set()
    seen = set()
    for row in db.execute('SELECT entity_id,data FROM csm_entity_labels ORDER BY entity_id,revision DESC'):
        label = json.loads(row['data'])
        entity_id = row['entity_id']
        if entity_id in seen or not label['source_digests'].keys() <= visible:
            continue
        verify_entity_evidence(db, label, cutoff)
        seen.add(entity_id)
        if len(label['label'].strip()) >= 2 and label['label'] in text:
            owners.add('entity:' + entity_id)
    return owners


def _project(service, *, now, source_until, visible_source_ids, temporal_kind, owner_ref=None, binding_key=None,
             include_applicability=False, source_refs=None, binding_keys=None, mention_text=None):
    clock = _instant(now, 'now')
    cutoff = _instant(source_until, 'source_until')
    require(temporal_kind in (None, 'appointment', 'deadline'), 'commitment_temporal_kind_invalid')
    require(cutoff <= clock, 'commitment_cutoff_after_clock')
    visible = None if visible_source_ids is None else frozenset(visible_source_ids)
    latest = {}
    matched = {}
    with _snapshot(service.store) as db:
        _ready(db)
        if mention_text is not None:
            owners = _mentioned_owners(db, mention_text, cutoff=cutoff, visible=visible)
            if not owners:
                return []
        for row in db.execute('SELECT binding_key,data FROM csm_property_commits ORDER BY seq'):
            if binding_key is not None and row['binding_key'] != binding_key:
                continue
            if binding_keys is not None and row['binding_key'] not in binding_keys:
                continue
            receipt = json.loads(row['data'])
            binding = receipt['binding']
            if binding['property_key'] != PROPERTY_KEY:
                continue
            if owner_ref is not None and binding['owner_ref'] != owner_ref:
                continue
            if mention_text is not None and binding['owner_ref'] not in owners:
                continue
            head, seals = receipt['head'], receipt['source_seals']
            require(bool(seals) and digest(head) == receipt['head_digest'], 'commitment_receipt_invalid')
            if visible is not None and not seals.keys() <= visible:
                continue
            observed = [db.execute('SELECT observed_at FROM events WHERE id=?', (ref,)).fetchone()
                        for ref in seals]
            require(all(r is not None for r in observed), 'evidence_source_unknown')
            if any(r[0] is None or parse_instant(r[0]) > cutoff for r in observed):
                continue
            _verify_seals(db, seals)
            effective = _instant(head['valid_from'], 'valid_from')
            if effective > clock:
                continue
            key = row['binding_key']
            latest[key] = receipt
            if source_refs is not None and source_refs & seals.keys():
                proposal = _proposal(db, receipt['proposal_id'], receipt['proposal_digest'])
                for span in proposal['payload']['binding']['evidence']:
                    ref = span['event_id']
                    if ref in source_refs:
                        matched.setdefault(key, {})[(ref, tuple(span['path']), span['quote'])] = span

        states = []
        include_applicability = include_applicability or binding_key is not None
        for key, receipt in latest.items():
            if source_refs is not None and key not in matched:
                continue
            head = receipt['head']
            value = head['value']
            start, end = validate_commitment(value)
            applicability = _applicability(value, clock, start, end)
            if ((temporal_kind is None or value.get('temporal_kind', 'appointment') == temporal_kind)
                    and (include_applicability or applicability in ('DUE', 'DEADLINE_DATE'))):
                proposal = _proposal(db, receipt['proposal_id'], receipt['proposal_digest'])
                evidence = proposal['payload']['binding']['evidence']
                require('date_evidence' not in value or value['date_evidence'] in evidence,
                        'commitment_date_evidence_unbound')
                states.append({'binding_key': key, 'owner_ref': receipt['binding']['owner_ref'],
                            'revision': head['revision'], 'commitment': value,
                            'source_refs': head['source_refs'], 'proposal_id': receipt['proposal_id'],
                            'evidence': evidence,
                            **({'matched_source_refs': sorted({ref for ref, _, _ in matched[key]}),
                                'matched_evidence': list(matched[key].values())}
                               if source_refs is not None else {}),
                            **({'applicability': applicability} if include_applicability else {}),
                            'state_scope': 'reviewed_source_claim', 'confirmed': False})
    return sorted(states, key=lambda item: (_instant(item['commitment']['due_start'], 'due_start'),
                                         item['binding_key']))
