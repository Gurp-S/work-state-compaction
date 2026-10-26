DB_NAME = 'booking.sqlite3'
ENDPOINT = '/api/bookings'
SEED = {'resource_id': 'room-a', 'start': '2026-10-22T02:00:00Z', 'end': '2026-10-22T03:00:00Z', 'state': 'confirmed'}
"""Runnable v1 read-only prototype. Persistent payloads are the migration input."""
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / DB_NAME
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO records VALUES(?,?)', ('welcome', json.dumps(SEED, ensure_ascii=False)))
            if db.execute('PRAGMA user_version').fetchone()[0] == 0:
                db.execute('PRAGMA user_version=1')

    def request(self, method, path, body, token):
        path = urlsplit(path).path
        if method == 'GET' and path == '/api/health':
            return 200, {'ok': True, 'schema': 1}
        if method == 'GET' and path == ENDPOINT:
            with sqlite3.connect(self.db) as db:
                items = [dict(id=row[0], **json.loads(row[1])) for row in db.execute('SELECT id,payload FROM records ORDER BY id')]
            return 200, {'items': items, 'next_cursor': None}
        return 404, {'error': 'not_found'}
