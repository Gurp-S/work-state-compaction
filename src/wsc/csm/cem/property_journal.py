"""Opt-in reviewed property commits: binding, value and membership in one transaction.

Reviews record caller judgments, not engine-verified entailment. Legacy state and
graph paths are unchanged; this journal detects writes that bypass its boundary.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from types import SimpleNamespace
from uuid import uuid4

from ..contracts import digest, encode
from . import explicit_write, identity, state
from ..contracts import MemoryCandidate, require, anchors, normalize
from .entity_registry import _ready as entity_ready, _provenance, _verify, require_entity
from .semantic_contract import (PropertySpec, PropertyBinding, RelationClaim, SourceSpan,
                                plan, validate_spec)
from ..store import getmeta, setmeta

POLICY = 'reviewed-property-journal-v1'
TABLES = ('csm_property_specs', 'csm_property_bindings', 'csm_property_proposals',
          'csm_property_reviews', 'csm_property_commits', 'csm_property_relation_events')
SCHEMA = (
 'CREATE TABLE csm_property_specs (key TEXT PRIMARY KEY, digest TEXT NOT NULL, data TEXT NOT NULL)',
 'CREATE TABLE csm_property_bindings (binding_key TEXT PRIMARY KEY, memory_id TEXT NOT NULL UNIQUE, data TEXT NOT NULL)',
 'CREATE TABLE csm_property_proposals (proposal_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, data TEXT NOT NULL)',
 'CREATE TABLE csm_property_reviews (proposal_id TEXT PRIMARY KEY, data TEXT NOT NULL)',
 'CREATE TABLE csm_property_commits (seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL UNIQUE, binding_key TEXT NOT NULL, data TEXT NOT NULL)',
 'CREATE TABLE csm_property_relation_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL, binding_key TEXT NOT NULL, member_ref TEXT NOT NULL, data TEXT NOT NULL)',
)


def _slot(key):
    # Opaque registry keys do not inherit the legacy display-slot normalization.
    return 'property_' + digest({'property_key': key})


def _ready(db):
    entity_ready(db)
    require(getmeta(db, 'property_journal_format') == {'version': 1}, 'property_journal_not_initialized')
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(set(TABLES) <= names, 'property_journal_format_invalid')


def _spans(values):
    return tuple(SourceSpan(s['event_id'], tuple(s['path']), s['quote']) for s in values)


class _ConnectionView:
    def __init__(self, db): self.db = db
    @contextmanager
    def connect(self): yield self.db


@contextmanager
def _snapshot(store):
    with store.connect() as db:
        owned = not db.in_transaction
        if owned: db.execute('BEGIN')
        try: yield db
        finally:
            if owned: db.execute('ROLLBACK')


def _planned(db, payload):
    fields = payload['binding']
    binding = PropertyBinding(**{**fields, 'contexts': tuple(fields['contexts']),
                                 'evidence': _spans(fields['evidence'])})
    relations = tuple(RelationClaim(**{**r, 'contexts': tuple(r['contexts']),
                                      'evidence': _spans(r['evidence'])}) for r in payload['relations'])
    return plan(SimpleNamespace(store=_ConnectionView(db)), PropertySpec(**payload['spec']), binding,
        MemoryCandidate(**payload['candidate']), operation=payload['operation'], relations=relations,
        coverage=payload['coverage'], coverage_evidence=_spans(payload['coverage_evidence']),
        until=payload['until'], entity_ids=True)


def _seals(db, ids):
    out = {}
    for ref in ids:
        row = db.execute('SELECT data,digest FROM events WHERE id=?', (ref,)).fetchone()
        require(row is not None, 'evidence_source_unknown')
        require(digest(json.loads(row['data'])) == row['digest'], 'evidence_source_digest_mismatch')
        out[ref] = row['digest']
    return out


def _verify_seals(db, seals):
    require(_seals(db, seals) == seals, 'property_proposal_source_changed')


def _entity_sources(db, checked):
    refs = {checked['binding']['owner_ref']}
    if checked['property']['cardinality'] == 'set':
        refs.update(checked['candidate']['value'])
        refs.update(checked['binding']['expected_value'] or [])
    return {event_id for ref in refs for event_id in require_entity(db, ref)['source_digests']}


def _spec(db, key):
    row = db.execute('SELECT digest,data FROM csm_property_specs WHERE key=?', (key,)).fetchone()
    require(row is not None, 'property_spec_unregistered')
    data = json.loads(row['data']); _verify(db, data)
    require(digest(data['spec']) == row['digest'], 'property_spec_digest_mismatch')
    return data


def _proposal(db, proposal_id, expected_digest):
    row = db.execute('SELECT digest,data FROM csm_property_proposals WHERE proposal_id=?', (proposal_id,)).fetchone()
    require(row is not None, 'property_proposal_unknown')
    require(row['digest'] == expected_digest, 'property_proposal_digest_mismatch')
    data = json.loads(row['data'])
    require(digest(data) == expected_digest, 'property_proposal_digest_mismatch')
    _verify_seals(db, data['source_seals'])
    require(digest(_spec(db, data['payload']['spec']['key'])['spec']) == data['plan']['property_schema_digest'],
            'property_spec_digest_mismatch')
    return data


def _bound(db, binding_key):
    row = db.execute('SELECT data FROM csm_property_bindings WHERE binding_key=?', (binding_key,)).fetchone()
    if row is None: return None
    binding = json.loads(row['data'])
    require(digest(_spec(db, binding['property_key'])['spec']) == binding['property_schema_digest'],
            'property_spec_digest_mismatch')
    require_entity(db, binding['owner_ref'])
    owner = identity.identity_row(db, binding['memory_id'])
    require(not owner.get('merged_into'), 'property_target_merged')
    require(owner['entity'] == normalize(binding['owner_ref'])
            and owner['slot'] == _slot(binding['property_key'])
            and anchors(owner['contexts'], field='context') == anchors(binding['contexts'], field='context'),
            'property_identity_outside_journal')
    last = db.execute('SELECT data FROM csm_property_commits WHERE binding_key=? ORDER BY seq DESC LIMIT 1',
                      (binding_key,)).fetchone()
    require(last is not None, 'property_journal_head_missing')
    committed = json.loads(last['data'])
    require(digest(state.head(db, binding['memory_id'])) == committed['head_digest'],
            'property_state_outside_journal')
    _verify_seals(db, committed['source_seals'])
    return binding


class PropertyJournal:
    def __init__(self, service): self.service = service

    def initialize(self):
        with self.service.store.transaction() as db:
            entity_ready(db)
            if getmeta(db, 'property_journal_format') is not None:
                _ready(db); return {'changed': False, 'policy': POLICY}
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require(not set(TABLES).intersection(names), 'property_journal_format_invalid')
            for statement in SCHEMA: db.execute(statement)
            setmeta(db, 'property_journal_format', {'version': 1})
            return {'changed': True, 'policy': POLICY}

    def register(self, spec, *, evidence, producer='caller'):
        validate_spec(spec)
        from .commitment_projection import PROPERTY_KEY
        if spec.key == PROPERTY_KEY:
            require(spec.cardinality == 'single', 'commitment_cardinality_invalid')
        require(spec.cardinality != 'observation', 'property_journal_observation_not_state')
        with self.service.store.transaction() as db:
            _ready(db)
            provenance = _provenance(db, evidence)
            definition = asdict(spec); fingerprint = digest(definition)
            row = db.execute('SELECT digest FROM csm_property_specs WHERE key=?', (spec.key,)).fetchone()
            if row:
                require(row['digest'] == fingerprint, 'property_spec_conflict')
                return {**_spec(db, spec.key), 'changed': False}
            data = {'spec': definition, 'recorded_at': self.service.clock(), 'producer': producer, **provenance}
            db.execute('INSERT INTO csm_property_specs VALUES(?,?,?)', (spec.key, fingerprint, encode(data)))
            return {**data, 'changed': True}

    def propose(self, *, request_id, spec_key, binding, candidate, operation=None,
                relations=(), coverage='partial', coverage_evidence=(), until=None):
        from .commitment_projection import PROPERTY_KEY, validate_commitment
        if spec_key == PROPERTY_KEY:
            validate_commitment(candidate.value)
            require(bool(candidate.valid_from), 'commitment_effective_time_missing')
        require(isinstance(request_id, str) and bool(request_id.strip()), 'property_request_id_missing')
        require(operation != 'observe', 'property_journal_observation_not_state')
        with self.service.store.transaction() as db:
            _ready(db)
            payload = {'spec': _spec(db, spec_key)['spec'], 'binding': asdict(binding),
                'candidate': asdict(candidate), 'operation': operation,
                'relations': [asdict(r) for r in relations], 'coverage': coverage,
                'coverage_evidence': [asdict(s) for s in coverage_evidence], 'until': until}
            # Normalize tuples through the durable JSON format before hashing/replay.
            payload = json.loads(encode(payload))
            existing = db.execute('SELECT proposal_id,digest,data FROM csm_property_proposals WHERE request_id=?',
                                  (request_id,)).fetchone()
            if existing:
                old = _proposal(db, existing['proposal_id'], existing['digest'])
                require(old['payload'] == payload, 'property_request_conflict')
                return {'proposal_id': existing['proposal_id'], 'digest': existing['digest'],
                        'plan': old['plan'], 'changed': False}
            checked = _planned(db, payload)
            registered = _bound(db, checked['binding_key'])
            if registered:
                require(binding.memory_id == registered['memory_id'], 'property_binding_conflict')
            elif operation != 'create' and binding.memory_id is not None:
                require(False, 'property_binding_unregistered')
            spec_sources = [s['event_id'] for s in _spec(db, spec_key)['evidence']]
            data = {'payload': payload, 'plan': checked,
                    'source_seals': _seals(db, [*checked['source_refs'], *spec_sources,
                                               *_entity_sources(db, checked)]),
                    'recorded_at': self.service.clock(), 'policy': POLICY}
            proposal_id = 'prp_' + uuid4().hex
            fingerprint = digest(data)
            db.execute('INSERT INTO csm_property_proposals VALUES(?,?,?,?)',
                       (proposal_id, request_id, fingerprint, encode(data)))
            return {'proposal_id': proposal_id, 'digest': fingerprint, 'plan': checked, 'changed': True}

    def review(self, proposal_id, *, expected_digest, decision, reviewer, reason, evidence):
        require(decision in ('accepted', 'rejected'), 'property_review_decision_invalid')
        require(isinstance(reviewer, str) and bool(reviewer.strip()) and isinstance(reason, str)
                and bool(reason.strip()), 'property_review_attribution_missing')
        with self.service.store.transaction() as db:
            _ready(db); proposal = _proposal(db, proposal_id, expected_digest)
            require(db.execute('SELECT 1 FROM csm_property_reviews WHERE proposal_id=?', (proposal_id,)).fetchone()
                    is None, 'property_review_already_recorded')
            if decision == 'accepted':
                require(proposal['plan']['status'] == 'structurally_valid', 'property_proposal_incomplete')
            provenance = _provenance(db, evidence)
            require(set(provenance['source_digests']) <= set(proposal['source_seals']),
                    'property_review_evidence_outside_proposal')
            data = {'proposal_id': proposal_id, 'proposal_digest': expected_digest, 'decision': decision,
                    'reviewer': reviewer, 'reason': reason, 'recorded_at': self.service.clock(),
                    'review_scope': 'caller_judgment_not_engine_entailment', **provenance}
            db.execute('INSERT INTO csm_property_reviews VALUES(?,?)', (proposal_id, encode(data)))
            return data

    def commit(self, proposal_id, *, expected_digest, producer='caller'):
        with self.service.store.transaction() as db:
            _ready(db); proposal = _proposal(db, proposal_id, expected_digest)
            reviewed = db.execute('SELECT data FROM csm_property_reviews WHERE proposal_id=?', (proposal_id,)).fetchone()
            require(reviewed is not None, 'property_review_missing')
            review = json.loads(reviewed['data']); _verify(db, review)
            require(review['decision'] == 'accepted' and review['proposal_digest'] == expected_digest,
                    'property_review_not_accepted')
            existing = db.execute('SELECT data FROM csm_property_commits WHERE proposal_id=?', (proposal_id,)).fetchone()
            if existing:
                old = json.loads(existing['data']); _verify_seals(db, old['source_seals'])
                return {**old, 'changed': False}
            checked = _planned(db, proposal['payload'])
            require(digest(checked) == digest(proposal['plan']), 'property_proposal_stale')
            require(checked['status'] == 'structurally_valid', 'property_proposal_incomplete')
            key, operation = checked['binding_key'], checked['operation']
            binding = _bound(db, key)
            if operation == 'create':
                require(binding is None, 'property_binding_exists')
            else:
                require(binding is not None and binding['memory_id'] == checked['binding']['memory_id'],
                        'property_binding_unregistered')
            candidate = MemoryCandidate(**checked['candidate'])
            sources = list(dict.fromkeys([*checked['source_refs'], *proposal['source_seals'],
                                          *(s['event_id'] for s in review['evidence'])]))
            candidate = replace(candidate, entity=checked['binding']['owner_ref'], slot=_slot(checked['property']['key']),
                contexts=tuple(checked['binding']['contexts']), source_ids=tuple(sources))
            previous = None if binding is None else state.head(db, binding['memory_id'])
            # Reuse the existing state reducer inside THIS transaction, never its outer wrapper.
            result = explicit_write._apply(db, self.service, candidate, operation=operation,
                target_memory_id=None if binding is None else binding['memory_id'],
                binding_source_ids=() if binding is None else tuple(sources), producer=producer)
            head = state.head(db, result['memory_id'])
            if binding is None:
                binding = {'binding_key': key, 'memory_id': result['memory_id'], 'owner_ref': checked['binding']['owner_ref'],
                    'property_key': checked['property']['key'], 'property_schema_digest': checked['property_schema_digest'],
                    'contexts': checked['binding']['contexts'], 'created_by_proposal': proposal_id}
                db.execute('INSERT INTO csm_property_bindings VALUES(?,?,?)', (key, result['memory_id'], encode(binding)))
            if checked['property']['cardinality'] == 'set':
                events = []
                for relation in checked['relations']:
                    member = relation['object'] if checked['property']['owner_role'] == 'subject' else relation['subject']
                    events.append({'member_ref': member, 'effect': relation['effect'], 'evidence': relation['evidence'],
                                   'derivation': 'explicit_relation_claim'})
                if operation == 'replace':
                    for member in previous['value']:
                        if member not in head['value']:
                            events.append({'member_ref': member, 'effect': 'end', 'evidence': checked['coverage_evidence'],
                                           'derivation': 'caller_complete_snapshot_exclusion'})
                for event in events:
                    data = {**event, 'valid_from': candidate.valid_from, 'memory_revision': head['revision'],
                            'owner_ref': binding['owner_ref'], 'property_key': binding['property_key'],
                            'kind': checked['property']['relation_kind'], 'owner_role': checked['property']['owner_role'],
                            'contexts': binding['contexts'], 'confirmed': False, 'semantic_support': 'not_verified'}
                    data['source_seals'] = _seals(db, (s['event_id'] for s in event['evidence']))
                    db.execute('INSERT INTO csm_property_relation_events(proposal_id,binding_key,member_ref,data) '
                               'VALUES(?,?,?,?)', (proposal_id, key, event['member_ref'], encode(data)))
                active = self._active(db, key)
                require(set(active) == set(head['value']), 'property_relation_state_mismatch')
            receipt = {'policy': POLICY, 'proposal_id': proposal_id, 'proposal_digest': expected_digest,
                'binding': binding, 'result': result, 'head': head, 'head_digest': digest(head),
                'source_seals': _seals(db, list(dict.fromkeys([*sources, *head['source_refs']]))), 'review': review,
                'state_scope': 'committed_identity_revision_not_world_confirmation',
                'semantic_support': 'not_verified', 'classification': 'UNKNOWN', 'confirmed': False,
                'world_total': None, 'completeness': 'not_established', 'changed': True}
            db.execute('INSERT INTO csm_property_commits(proposal_id,binding_key,data) VALUES(?,?,?)',
                       (proposal_id, key, encode(receipt)))
            return receipt

    @staticmethod
    def _active(db, key):
        members = {}
        for row in db.execute('SELECT member_ref,data FROM csm_property_relation_events WHERE binding_key=? ORDER BY seq', (key,)):
            event = json.loads(row['data'])
            _verify_seals(db, event['source_seals'])
            if event['effect'] == 'assert': members[row['member_ref']] = event
            else: members.pop(row['member_ref'], None)
        return members

    def inspect(self, binding_key):
        with _snapshot(self.service.store) as db:
            _ready(db); binding = _bound(db, binding_key)
            require(binding is not None, 'property_binding_unregistered')
            current = state.head(db, binding['memory_id'])
            active = self._active(db, binding_key)
            if _spec(db, binding['property_key'])['spec']['cardinality'] == 'set':
                require(set(active) == set(current['value']), 'property_relation_state_mismatch')
                for member in current['value']: require_entity(db, member)
            return {'binding': binding, 'head': current,
                    'active_members': active, 'world_total': None,
                    'semantic_support': 'not_verified', 'confirmed': False, 'completeness': 'not_established'}
