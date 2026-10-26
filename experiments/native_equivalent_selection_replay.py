"""Opt-in replay of unpublished selection state onto source-equivalent copies.

This is not live runtime recovery: published heads, cursors, runtime generations and
unsettled operations are rejected. The old store and model prose stay immutable.
"""
from dataclasses import fields
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from native_application_session import NativeApplicationSession
from native_evidence import file_hash
from wsc import WSC, Store, events
from wsc.contracts import Event, Understanding, Selection, Limits, digest, encode
from wsc.excerpts import Excerpt


def replay(source_database, previous, source_registration, target_database, target_registration, *, session_id):
    source_database, target_database = Path(source_database), Path(target_database)
    if target_database.exists():
        raise ValueError('selection_replay_target_exists')
    measured = NativeApplicationSession.source_manifest(SimpleNamespace(registration=target_registration))
    if measured != source_registration['initial_manifest'] or measured != target_registration['initial_manifest']:
        raise ValueError('selection_replay_source_not_equivalent')
    before_hash = file_hash(source_database)
    with closing(sqlite3.connect('file:' + str(source_database) + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        meta = {r['key']: json.loads(r['value']) for r in db.execute('SELECT key,value FROM meta')}
        binding = meta['binding']
        if (binding['workspace'] != previous['workspace'] or binding['session_id'] != previous['session_id']
                or str(Path(source_registration['workspace']).resolve()) != binding['workspace']):
            raise ValueError('selection_replay_origin_binding_changed')
        if (any(meta[key] != 0 for key in ('generation', 'cursor'))
                or meta['head'] is not None or meta['mode'] != 'active'
                or db.execute("SELECT 1 FROM usage WHERE status='started'").fetchone()
                or db.execute("SELECT 1 FROM operations WHERE state!='cancelled'").fetchone()):
            raise ValueError('selection_replay_requires_unpublished_closed_state')
        rows = events.rows(db)
        records = [json.loads(r[0]) for r in db.execute('SELECT data FROM understandings ORDER BY id,revision')]
        presentations = [(r['id'], json.loads(r['data'])) for r in db.execute('SELECT id,data FROM presentations')]
        row = db.execute('SELECT data FROM views WHERE id=?', (previous['view_id'],)).fetchone()
        if row is None:
            raise ValueError('selection_replay_previous_view_missing')
        original = json.loads(row[0])
    if (len(rows) != previous['cut'] or digest(rows) != previous['source_digest']
            or original['binding']['source_digest'] != previous['source_digest']
            or [r['ref'] for r in original['body']['understandings']] != previous['understanding_refs']):
        raise ValueError('selection_replay_prefix_changed')
    core = WSC(Store(target_database, session_id=session_id, workspace=target_registration['workspace']), access=lambda *a: True)
    keys = {f.name for f in fields(Event)}
    core.ingest([Event(**{key: r[key] for key in keys}) for r in rows])
    for identity, value in presentations:
        core.presented(identity, tuple(value['source_ids']), receiver=value['receiver'])
    for record in records:
        value = Understanding(record['text'], record['kind'], tuple(record['sources']), record['scope'],
            record['id'], record['revision'] - 1 if record['revision'] > 1 else None)
        if encode(core.remember(value, producer=record['producer'])) != encode(record):
            raise ValueError('selection_replay_record_changed')
    snapshot = core.capture()
    body = original['body']
    view = core.prepare(snapshot, Selection(tuple(r['id'] for r in body['sources']),
        tuple(previous['understanding_refs']), clues=tuple(body['clues']),
        excerpts=tuple(Excerpt(**r) for r in previous['excerpts'])),
        producer=original['producer'], source_projection=body.get('source_projection'),
        limits=Limits(max_view_bytes=131072))
    with core.store.connect() as db:
        rebuilt = json.loads(db.execute('SELECT data FROM views WHERE id=?', (view,)).fetchone()[0])
    if (rebuilt['body'] != body or tuple(rows) != snapshot.events or tuple(records) != snapshot.understandings
            or snapshot.control_epoch != meta['control_epoch']
            or snapshot.understanding_epoch != meta['understanding_epoch']):
        raise ValueError('selection_replay_material_changed')
    if file_hash(source_database) != before_hash:
        raise ValueError('selection_replay_origin_store_changed')
    rebased = {**previous, 'session_id': session_id, 'workspace': core.store.workspace, 'view_id': view}
    proof = dict(original_database_sha256=before_hash, original_workspace=binding['workspace'],
        receiving_workspace=core.store.workspace, source_digest=snapshot.source_digest,
        original_events_preserved=len(rows), original_record_versions_preserved=len(records),
        selected_body_identical=True, source_equivalent=True, published_runtime_imported=False,
        original_store_unchanged=True)
    return core, rebased, proof
