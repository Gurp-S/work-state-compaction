"""Explicit opt-in stable entity IDs, independent of names and retrieval nodes.

No automatic alias, object merge, tree redirect, or old-memory migration. All
declarations retain literal provenance; source integrity is not entailment.
"""
import json
import re
from uuid import uuid4

from ..contracts import digest, encode
from ..contracts import normalize, require
from .semantic_contract import SourceSpan, _spans
from ..store import getmeta, setmeta

POLICY = 'explicit-entity-registry-v1'
FORMAT = {'version': 1}
TABLE_NAMES = ('csm_entities', 'csm_entity_labels', 'csm_entity_nodes', 'csm_entity_node_history')
SCHEMA = (
    'CREATE TABLE csm_entities (entity_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, '
    'request_digest TEXT NOT NULL, data TEXT NOT NULL)',
    'CREATE TABLE csm_entity_labels (entity_id TEXT NOT NULL, revision INTEGER NOT NULL, '
    'label_key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(entity_id,revision))',
    'CREATE TABLE csm_entity_nodes (node_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, '
    'revision INTEGER NOT NULL, active INTEGER NOT NULL, data TEXT NOT NULL)',
    'CREATE TABLE csm_entity_node_history (node_id TEXT NOT NULL, revision INTEGER NOT NULL, '
    'data TEXT NOT NULL, PRIMARY KEY(node_id,revision))',
)


def _ready(db):
    require(getmeta(db, 'entity_registry_format') == FORMAT, 'entity_registry_not_initialized')
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    require(set(TABLE_NAMES) <= tables, 'entity_registry_format_invalid')


def _provenance(db, evidence):
    require(isinstance(evidence, (list, tuple)) and bool(evidence), 'entity_evidence_missing')
    spans = _spans(db, evidence, None)
    seals = {s['event_id']: db.execute('SELECT digest FROM events WHERE id=?',
             (s['event_id'],)).fetchone()[0] for s in spans}
    return {'evidence': spans, 'source_digests': seals, 'attribution': 'caller_declared',
            'semantic_support': 'not_verified', 'confirmed': False}


def _verify(db, data, cutoff=None):
    _spans(db, tuple(SourceSpan(s['event_id'], tuple(s['path']), s['quote'])
                     for s in data['evidence']), cutoff)
    for event_id, seal in data['source_digests'].items():
        row = db.execute('SELECT digest FROM events WHERE id=?', (event_id,)).fetchone()
        require(row is not None and row[0] == seal, 'entity_source_seal_mismatch')


def require_entity(db, ref, *, cutoff=None):
    """Validate a declared entity reference; never follow names or tree nodes."""
    _ready(db)
    require(isinstance(ref, str) and re.fullmatch(r'entity:ent_[0-9a-f]{32}', ref) is not None,
            'entity_ref_invalid')
    row = db.execute('SELECT data FROM csm_entities WHERE entity_id=?', (ref[7:],)).fetchone()
    require(row is not None, 'entity_ref_unknown')
    data = json.loads(row['data']); _verify(db, data, cutoff)
    return data


def _label(db, entity_id):
    row = db.execute('SELECT data FROM csm_entity_labels WHERE entity_id=? '
                     'ORDER BY revision DESC LIMIT 1', (entity_id,)).fetchone()
    require(row is not None, 'entity_label_missing')
    data = json.loads(row['data']); _verify(db, data)
    return data


def _node(db, node_id, *, active=True):
    require(isinstance(node_id, str) and bool(node_id), 'entity_node_invalid')
    row = db.execute('SELECT node_type,status FROM tree_nodes WHERE node_id=?', (node_id,)).fetchone()
    require(row is not None and row['node_type'] == 'entity', 'entity_node_invalid')
    if active:
        require(row['status'] == 'active', 'entity_node_unavailable')
    return row


class EntityRegistry:
    def __init__(self, service):
        self.service = service  # Construction is read-only; initialization is explicit.

    def initialize(self):
        with self.service.store.transaction() as db:
            if getmeta(db, 'entity_registry_format') is not None:
                _ready(db)
                return {'policy': POLICY, 'changed': False}
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require(not tables.intersection(TABLE_NAMES), 'entity_registry_format_invalid')
            for statement in SCHEMA:
                db.execute(statement)
            setmeta(db, 'entity_registry_format', FORMAT)
            return {'policy': POLICY, 'changed': True}

    def create(self, *, request_id, label, evidence, producer='model'):
        require(isinstance(request_id, str) and bool(request_id.strip()), 'entity_request_id_missing')
        label_key = normalize(label, field='entity_label')
        with self.service.store.transaction() as db:
            _ready(db)
            provenance = _provenance(db, evidence)
            request_digest = digest({'label': label, 'provenance': provenance, 'producer': producer})
            previous = db.execute('SELECT entity_id,request_digest,data FROM csm_entities WHERE request_id=?',
                                  (request_id,)).fetchone()
            if previous:
                require(previous['request_digest'] == request_digest, 'entity_request_conflict')
                data = require_entity(db, 'entity:' + previous['entity_id'])
                return {**data, 'changed': False}
            entity_id = 'ent_' + uuid4().hex
            now = self.service.clock()
            data = {'entity_id': entity_id, 'ref': 'entity:' + entity_id, 'request_id': request_id,
                    'created_at': now, 'producer': producer, 'policy': POLICY, **provenance}
            db.execute('INSERT INTO csm_entities VALUES(?,?,?,?)',
                       (entity_id, request_id, request_digest, encode(data)))
            name = {'entity_id': entity_id, 'revision': 1, 'label': label,
                    'recorded_at': now, 'producer': producer, **provenance}
            db.execute('INSERT INTO csm_entity_labels VALUES(?,?,?,?)', (entity_id, 1, label_key, encode(name)))
            return {**data, 'changed': True}

    def get(self, ref, *, history=False):
        with self.service.store.connect() as db:
            data = require_entity(db, ref)
            result = {**data, 'current_label': _label(db, data['entity_id'])}
            if history:
                names = [json.loads(row['data']) for row in db.execute(
                    'SELECT data FROM csm_entity_labels WHERE entity_id=? ORDER BY revision', (data['entity_id'],))]
                for name in names: _verify(db, name)
                result['label_history'] = names
            return result

    def set_label(self, ref, *, label, expected_revision, evidence, producer='model'):
        require(type(expected_revision) is int and expected_revision > 0, 'entity_label_revision_invalid')
        label_key = normalize(label, field='entity_label')
        with self.service.store.transaction() as db:
            entity = require_entity(db, ref)
            previous = _label(db, entity['entity_id'])
            require(previous['revision'] == expected_revision, 'entity_label_revision_conflict')
            provenance = _provenance(db, evidence)
            data = {'entity_id': entity['entity_id'], 'revision': expected_revision + 1, 'label': label,
                    'recorded_at': self.service.clock(), 'producer': producer, **provenance}
            db.execute('INSERT INTO csm_entity_labels VALUES(?,?,?,?)',
                       (entity['entity_id'], data['revision'], label_key, encode(data)))
            return data

    def find_label(self, label):
        """All exact normalized current-label matches; multiple matches stay separate."""
        label_key = normalize(label, field='entity_label')
        with self.service.store.connect() as db:
            _ready(db)
            rows = db.execute('SELECT l.entity_id,l.data FROM csm_entity_labels l WHERE l.label_key=? '
                'AND l.revision=(SELECT max(x.revision) FROM csm_entity_labels x WHERE x.entity_id=l.entity_id) '
                'ORDER BY l.entity_id', (label_key,)).fetchall()
            out = []
            for row in rows:
                require_entity(db, 'entity:' + row['entity_id'])
                data = json.loads(row['data']); _verify(db, data); out.append(data)
            return {'matches': out, 'resolution': 'unique_label_candidate' if len(out) == 1 else
                    ('ambiguous' if out else 'not_found'), 'semantic_support': 'not_verified'}

    def _node_change(self, ref, node_id, evidence, expected_revision, *, active, producer):
        require(type(expected_revision) is int and expected_revision >= 0, 'entity_node_revision_invalid')
        with self.service.store.transaction() as db:
            entity = require_entity(db, ref)
            _node(db, node_id, active=active)
            row = db.execute('SELECT data FROM csm_entity_nodes WHERE node_id=?', (node_id,)).fetchone()
            previous = None if row is None else json.loads(row['data'])
            require((previous['revision'] if previous else 0) == expected_revision, 'entity_node_revision_conflict')
            if previous:
                _verify(db, previous)
            if active:
                require(not previous or not previous['active'], 'entity_node_binding_exists')
            else:
                require(previous is not None and previous['active'] and previous['entity_id'] == entity['entity_id'],
                        'entity_node_binding_mismatch')
            data = {'entity_id': entity['entity_id'], 'node_id': node_id, 'revision': expected_revision + 1,
                    'active': active, 'recorded_at': self.service.clock(), 'producer': producer,
                    **_provenance(db, evidence)}
            db.execute('INSERT INTO csm_entity_node_history VALUES(?,?,?)', (node_id, data['revision'], encode(data)))
            db.execute('INSERT INTO csm_entity_nodes VALUES(?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET '
                'entity_id=excluded.entity_id,revision=excluded.revision,active=excluded.active,data=excluded.data',
                (node_id, entity['entity_id'], data['revision'], int(active), encode(data)))
            return data

    def bind_node(self, ref, *, node_id, evidence, expected_revision=0, producer='model'):
        return self._node_change(ref, node_id, evidence, expected_revision, active=True, producer=producer)

    def unbind_node(self, ref, *, node_id, evidence, expected_revision, producer='model'):
        return self._node_change(ref, node_id, evidence, expected_revision, active=False, producer=producer)

    def resolve_node(self, node_id):
        with self.service.store.connect() as db:
            _ready(db); _node(db, node_id)
            row = db.execute('SELECT data FROM csm_entity_nodes WHERE node_id=? AND active=1', (node_id,)).fetchone()
            require(row is not None, 'entity_node_unbound')
            data = json.loads(row['data']); _verify(db, data)
            require_entity(db, 'entity:' + data['entity_id'])
            return data

    def node_history(self, node_id):
        with self.service.store.connect() as db:
            _ready(db)
            rows = [json.loads(row['data']) for row in db.execute(
                'SELECT data FROM csm_entity_node_history WHERE node_id=? ORDER BY revision', (node_id,))]
            for row in rows: _verify(db, row)
            return rows
