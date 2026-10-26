"""Author-only file protocol calibration; bytes persist in the local SQLite state."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit
import uuid

FAULT = 'none'


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.body = status, {'error': code}


def require(ok, status=400, code='invalid_request'):
    if not ok:
        raise Rejected(status, code)


def decoded(raw):
    return base64.b64decode(raw, validate=True)


def encoded(raw):
    return base64.b64encode(raw).decode()


def uid():
    return uuid.uuid4().hex


def valid_name(name):
    require(isinstance(name, str) and name and '..' not in name and '/' not in name and '\\' not in name)


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'files.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS calibration_state(id INTEGER PRIMARY KEY,payload TEXT)')
            if not db.execute('SELECT 1 FROM calibration_state WHERE id=1').fetchone():
                state = dict(files={}, uploads={}, shares={}, roles={'admin-a': 'admin', 'member-a': 'member', 'viewer-a': 'viewer', 'admin-b': 'admin'})
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                old = db.execute('SELECT id,payload FROM records').fetchall() if 'records' in tables else [
                    ('welcome', json.dumps(dict(name='README.txt', folder='/', content_b64=encoded(b'Welcome\n'), tags=[])))]
                for key, payload in old:
                    item = json.loads(payload)
                    raw = decoded(item.pop('content_b64'))
                    state['files'][key] = dict(item, id=key, tenant='tenant-a', size=len(raw), sha256=sha256(raw).hexdigest(),
                                              version=1, versions={'1': encoded(raw)}, deleted=False)
                db.execute('INSERT INTO calibration_state VALUES(1,?)', (json.dumps(state),))
                db.execute('PRAGMA user_version=2')

    def request(self, method, url, body, token):
        parsed = urlsplit(url)
        if method == 'GET' and parsed.path == '/api/health':
            return 200, dict(ok=True, schema=2)
        try:
            with sqlite3.connect(self.db, timeout=10) as db:
                db.execute('BEGIN IMMEDIATE')
                state = json.loads(db.execute('SELECT payload FROM calibration_state WHERE id=1').fetchone()[0])
                public = method == 'GET' and parsed.path.startswith('/api/shared/')
                require(public or token in state['roles'], 401, 'unauthorized')
                tenant = 'tenant-b' if token == 'admin-b' else 'tenant-a'
                if method != 'GET':
                    require(state['roles'][token] != 'viewer', 403, 'forbidden')
                result = self.route(state, method, parsed.path, parse_qs(parsed.query), body, token, tenant)
                if method != 'GET':
                    db.execute('UPDATE calibration_state SET payload=? WHERE id=1', (json.dumps(state),))
                return result
        except Rejected as error:
            return error.status, error.body
        except (ValueError, KeyError, TypeError):
            return 400, dict(error='invalid_request')

    def route(self, s, method, path, query, body, token, tenant):
        def get(collection, key, deleted=False):
            item = s[collection].get(key)
            require(item is not None and item['tenant'] == tenant, 404, 'not_found')
            require(deleted or not item.get('deleted', False), 404, 'not_found')
            return item

        def shown(item):
            return {k: v for k, v in item.items() if k != 'versions'}

        def versioned(item, raw=None):
            previous = item['versions'][str(item['version'])]
            item['version'] += 1
            item['versions'][str(item['version'])] = previous if raw is None else encoded(raw)

        if method == 'PATCH' and path == '/api/members/member-a':
            require(s['roles'][token] == 'admin', 403, 'forbidden')
            s['roles']['member-a'] = body['role']
            return 200, dict(role=body['role'])
        if method == 'POST' and path == '/api/uploads':
            valid_name(body['name'])
            require(body['folder'].startswith('/') and '..' not in body['folder'].split('/') and '\\' not in body['folder'])
            require(type(body['size']) is int and body['size'] >= 0 and len(body['sha256']) == 64)
            item = dict(body, id=uid(), tenant=tenant, offset=0, data_b64='', state='uploading')
            s['uploads'][item['id']] = item
            return 201, {k: v for k, v in item.items() if k != 'data_b64'}
        if path.startswith('/api/uploads/'):
            item = get('uploads', path.split('/')[3])
            if method == 'GET':
                return 200, {k: v for k, v in item.items() if k != 'data_b64'}
            if method == 'PATCH':
                require(item['state'] == 'uploading', 409, 'upload_closed')
                raw, chunk, offset = decoded(item['data_b64']), decoded(body['data_b64']), body['offset']
                require(type(offset) is int and offset >= 0)
                if offset < len(raw):
                    require(FAULT == 'accept_conflicting_chunk' or raw[offset:offset+len(chunk)] == chunk, 409, 'chunk_conflict')
                    return 200, dict(offset=len(raw))
                require(offset == len(raw), 409, 'offset_conflict')
                require(len(raw) + len(chunk) <= item['size'])
                item.update(data_b64=encoded(raw + chunk), offset=len(raw) + len(chunk))
                return 200, dict(offset=item['offset'])
            if method == 'POST' and path.endswith('/complete'):
                if item['state'] == 'completed':
                    return 200, shown(get('files', item['file_id']))
                raw = decoded(item['data_b64'])
                require(len(raw) == item['size'] and sha256(raw).hexdigest() == item['sha256'], 422, 'content_mismatch')
                fid = uid()
                file = dict(id=fid, name=item['name'], folder=item['folder'], tags=[], tenant=tenant,
                            size=len(raw), sha256=item['sha256'], version=1, versions={'1': encoded(raw)}, deleted=False)
                s['files'][fid] = file
                item.update(state='completed', file_id=fid)
                return 201, shown(file)
        if method == 'GET' and path in ('/api/files', '/api/trash'):
            rows = [shown(i) for i in s['files'].values() if i['tenant'] == tenant and i['deleted'] == (path == '/api/trash')]
            for field in ('folder', 'tag', 'q'):
                if field in query:
                    value = query[field][0]
                    rows = [i for i in rows if (value == i['folder'] if field == 'folder' else
                                               value in i['tags'] if field == 'tag' else value in i['name'])]
            rows.sort(key=lambda i: i['id'])
            start, limit = int(query.get('cursor', ['0'])[0]), int(query.get('limit', ['100'])[0])
            return 200, dict(items=rows[start:start+limit], next_cursor=str(start+limit) if start+limit < len(rows) else None)
        if path.startswith('/api/files/'):
            restoring = path.endswith('/restore')
            item = get('files', path.split('/')[3], deleted=restoring or FAULT == 'resurrection')
            if method == 'GET' and path.endswith('/content'):
                version = query.get('version', [str(item['version'])])[0]
                require(version in item['versions'], 404, 'version_not_found')
                return 200, dict(data_b64=item['versions'][version])
            if method == 'GET':
                return 200, shown(item)
            if method == 'POST' and restoring:
                require(item['version'] == body['version'], 409, 'version_conflict')
                item['deleted'] = False
                versioned(item)
                return 200, shown(item)
            expected = int(query['version'][0]) if method == 'DELETE' else body['version']
            require(item['version'] == expected or FAULT == 'resurrection', 409, 'version_conflict')
            if method == 'DELETE':
                item['deleted'] = True
                versioned(item)
                for share in s['shares'].values():
                    if share['file_id'] == item['id']:
                        share['revoked'] = True
                return 200, shown(item)
            if method == 'PATCH':
                if 'name' in body:
                    valid_name(body['name'])
                for key in ('name', 'folder', 'tags'):
                    if key in body:
                        item[key] = body[key]
                if FAULT == 'resurrection':
                    item['deleted'] = False
                versioned(item)
                return 200, shown(item)
            if method == 'POST' and path.endswith('/versions'):
                raw = decoded(body['data_b64'])
                require(sha256(raw).hexdigest() == body['sha256'], 422, 'content_mismatch')
                versioned(item, raw)
                item.update(size=len(raw), sha256=body['sha256'])
                return 201, shown(item)
        if method == 'DELETE' and path.startswith('/api/trash/'):
            item = get('files', path.split('/')[3], deleted=True)
            require(item['deleted'] and item['version'] == int(query['version'][0]), 409, 'version_conflict')
            del s['files'][item['id']]
            return 200, dict(id=item['id'])
        if method == 'POST' and path == '/api/shares':
            get('files', body['file_id'])
            sid = uid()
            s['shares'][sid] = dict(token=sid, file_id=body['file_id'], tenant=tenant, revoked=False)
            return 201, dict(token=sid)
        if method == 'DELETE' and path.startswith('/api/shares/'):
            share = get('shares', path.split('/')[3])
            share['revoked'] = True
            return 200, dict(ok=True)
        if method == 'GET' and path.startswith('/api/shared/'):
            share = s['shares'].get(path.split('/')[3])
            require(share is not None and not share['revoked'], 404, 'not_found')
            item = s['files'].get(share['file_id'])
            require(item is not None and not item['deleted'], 404, 'not_found')
            return 200, dict(data_b64=item['versions'][str(item['version'])])
        if method == 'POST' and path == '/api/maintenance/gc':
            require(s['roles'][token] == 'admin', 403, 'forbidden')
            for item in s['uploads'].values():
                if item['state'] == 'completed':
                    item['data_b64'] = ''
            if FAULT == 'drop_history':
                for item in s['files'].values():
                    item['versions'] = {str(item['version']): item['versions'][str(item['version'])]}
            return 200, dict(ok=True)
        return 404, dict(error='not_found')
