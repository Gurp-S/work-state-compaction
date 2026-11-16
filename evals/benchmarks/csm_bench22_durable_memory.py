"""Opt-in persistent original history for the offline Bench 2.2 adapter."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from csm_bench22_raw_memory import RawMemoryBench22
from wsc.contracts import digest
from wsc.csm import CsmStore


_NAMESPACE = 'bench22-raw-memory'


class DurableRawMemoryBench22(RawMemoryBench22):
    """One original history per database, with recall indexes rebuilt on open."""

    def __init__(self, path, **options):
        path = Path(path).resolve()
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                try:
                    row = db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
                except sqlite3.DatabaseError as exc:
                    raise ValueError('raw_memory_store_required') from exc
                if row is None or json.loads(row[0]) != {'schema': 1, 'namespace': _NAMESPACE}:
                    raise ValueError('raw_memory_store_required')
        super().__init__(store=CsmStore(path, namespace=_NAMESPACE), **options)
        with self.store.connect() as db:
            rows = db.execute('SELECT id, source_type, observed_at, data, digest FROM events ORDER BY seq')
            for seq, row in enumerate(rows, 1):
                source = json.loads(row['data'])
                if digest(source) != row['digest']:
                    raise ValueError('source_digest_mismatch')
                if (row['id'] != f'chat/{seq}' or row['source_type'] != 'chat'
                        or source['turn'] != seq or row['observed_at'] != source['time'].strip()):
                    raise ValueError('raw_memory_history_mismatch')
                self._index_source(source)

    def begin_tail(self):
        raise ValueError('raw_memory_branch_requires_in_memory_history')

    def rewind(self, token):
        raise ValueError('raw_memory_history_is_append_only')
