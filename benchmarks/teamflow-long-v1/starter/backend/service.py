"""Working single-workspace prototype; later contracts are intentionally absent."""
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'teamflow.sqlite3'
        with sqlite3.connect(self.db) as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS legacy_projects(id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS legacy_issues(id INTEGER PRIMARY KEY, project_id TEXT, title TEXT, status TEXT);
                INSERT OR IGNORE INTO legacy_projects VALUES('welcome','Welcome');
                PRAGMA user_version=1;
            ''')

    def request(self, method, path, body, token):
        path = urlsplit(path).path
        with sqlite3.connect(self.db) as connection:
            connection.row_factory = sqlite3.Row
            if method == 'GET' and path == '/api/health':
                return 200, {'ok': True, 'schema': 1}
            if method == 'GET' and path == '/api/projects':
                return 200, {'items': [dict(r) for r in connection.execute('SELECT * FROM legacy_projects ORDER BY id')]}
            if method == 'GET' and path == '/api/issues':
                return 200, {'items': [dict(r) for r in connection.execute('SELECT * FROM legacy_issues ORDER BY id')], 'next_cursor': None}
            if method == 'POST' and path == '/api/issues':
                cursor = connection.execute('INSERT INTO legacy_issues(project_id,title,status) VALUES(?,?,?)',
                                            (body['project_id'], body['title'], 'todo'))
                return 201, {'id': str(cursor.lastrowid), 'title': body['title'], 'status': 'todo', 'version': 1}
            return 404, {'error': 'not_found'}
