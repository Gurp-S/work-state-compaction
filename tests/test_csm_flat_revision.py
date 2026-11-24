from pathlib import Path
from tempfile import TemporaryDirectory

from wsc.csm import CSM, Event, MemoryQuery
from wsc.csm.cem.flat_revision import FlatRevisionMemory
from wsc.csm.store import CsmStore


def test_write_time_revisions_survive_sessions_and_separate_history():
    first = '2026-11-01T10:00:00+08:00'
    second = '2026-11-02T10:00:00+08:00'
    third = '2026-11-03T10:00:00+08:00'
    key = ('Project A', 'database', ('release',))
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / 'memory.sqlite3'
        csm = CSM(CsmStore(path, namespace='project'), clock=lambda: third)

        def interpret(event, candidates):
            if not candidates:
                return [dict(new_entity=key[0], slot=key[1], contexts=key[2],
                             value='MySQL', confidence=1)]
            return [dict(target=candidates[0]['memory_id'], value='PostgreSQL',
                         confidence=event.payload['confidence'])]

        writer = FlatRevisionMemory(csm, interpret)
        writer.consume(Event('session-a/1', 'chat', {'text': 'Project A uses MySQL'}, observed_at=first),
                       confirmed=True)
        writer.consume(Event('session-a/2', 'chat', {'text': 'Could switch to PostgreSQL', 'confidence': 0.8},
                             observed_at=second))
        reader = FlatRevisionMemory(CSM(CsmStore(path, namespace='project')), None)
        current, = reader.read(*key, now=second)
        assert (current['value'], current['classification']) == ('PostgreSQL', 'SPECULATIVE')
        assert reader.condition(*key, expected='PostgreSQL', now=first) == 'BLOCKED'
        assert reader.condition(*key, expected='PostgreSQL', now=second) == 'UNKNOWN'
        legacy, = csm.query(MemoryQuery(entity=key[0], slot=key[1], contexts=key[2]))['results']
        assert legacy['classification'] == 'SPECULATIVE' and not legacy['confirmed']
        writer.consume(Event('session-b/1', 'tool', {'text': 'PostgreSQL configured', 'confidence': 1},
                             observed_at=third), confirmed=True)
        current, = reader.read(*key, now=third)
        assert (current['revision'], current['value'], current['classification']) == (3, 'PostgreSQL', 'CURRENT_CONFIRMED')
        assert reader.condition(*key, expected='PostgreSQL', now=third) == 'READY'
        assert [row['classification'] for row in reader.read(*key, now=third, history=True)] == [
            'CURRENT_CONFIRMED', 'HISTORICAL', 'HISTORICAL']
        earlier, = reader.read(*key, now=third, visible_sources={'session-a/1'})
        assert earlier['value'] == 'MySQL'
        with csm.store.connect() as db:
            assert db.execute('SELECT count(*) FROM revisions').fetchone()[0] == 3
            assert db.execute('SELECT count(*) FROM pending').fetchone()[0] == 0


def test_unclear_binding_creates_a_temporary_speculative_head():
    now = '2026-11-01T10:00:00+08:00'
    with TemporaryDirectory() as temporary:
        csm = CSM(CsmStore(Path(temporary) / 'memory.sqlite3', namespace='project'))
        writer = FlatRevisionMemory(csm, lambda event, candidates: [
            dict(slot='deployment', value='done', confidence=0.4)])
        writer.consume(Event('chat/1', 'chat', {'text': 'That project is done'}, observed_at=now))
        row, = writer.read('temporary/chat/1', 'deployment', (), now=now)
        assert row['classification'] == 'SPECULATIVE'


def test_unoffered_reference_routes_from_the_observed_flat_key():
    now = '2026-11-01T10:00:00+08:00'
    with TemporaryDirectory() as temporary:
        csm = CSM(CsmStore(Path(temporary) / 'memory.sqlite3', namespace='project'))
        writer = FlatRevisionMemory(csm, lambda event, candidates: [
            dict(target='model-invented-id', new_entity='Harbor', slot='deployment', value='done',
                 confidence=0.95)])
        writer.consume(Event('chat/1', 'chat', {'text': 'Harbor deployment is done'}, observed_at=now))
        row, = writer.read('Harbor', 'deployment', (), now=now)
        assert row['classification'] == 'SPECULATIVE'
        assert row['source_refs'] == ['chat/1']


def test_write_side_offers_a_bounded_list_with_the_explicit_older_identity():
    now = '2026-11-01T10:00:00+08:00'
    with TemporaryDirectory() as temporary:
        csm = CSM(CsmStore(Path(temporary) / 'memory.sqlite3', namespace='project'))

        def interpret(event, candidates):
            if 'old' in event.payload:
                assert len(candidates) == 16
                assert candidates[0]['entity'] == 'harbor'
                return [dict(target=candidates[0]['memory_id'], value='PostgreSQL', confidence=0.9)]
            return [dict(new_entity=event.payload['text'], slot='database', value='MySQL', confidence=0.9)]

        memory = FlatRevisionMemory(csm, interpret)
        for index, name in enumerate(['Harbor', *(f'Service {i}' for i in range(20))]):
            memory.consume(Event(f'chat/{index}', 'chat', {'text': name}, observed_at=now))
        memory.consume(Event('chat/update', 'chat', {'text': 'Harbor changes database', 'old': True}, observed_at=now))
        row, = memory.read('Harbor', 'database', (), now=now)
        assert (row['value'], row['revision']) == ('PostgreSQL', 2)
