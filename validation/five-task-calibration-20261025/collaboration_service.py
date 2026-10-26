"""Author-only collaboration protocol calibration; excluded from task workspaces."""
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


def uid():
    return uuid.uuid4().hex


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'teamflow.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS calibration_state(id INTEGER PRIMARY KEY,payload TEXT)')
            old = db.execute('SELECT payload FROM calibration_state WHERE id=1').fetchone()
            if old and FAULT != 'migration_reset':
                return
            state = json.loads(old[0]) if old else dict(projects={}, issues={}, comments={}, batches={}, audit=[],
                roles={'admin-a': 'admin', 'member-a': 'member', 'viewer-a': 'viewer', 'admin-b': 'admin'})
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            projects = db.execute('SELECT id,name FROM legacy_projects').fetchall() if 'legacy_projects' in tables else [('welcome', 'Welcome')]
            for key, name in projects:
                state['projects'][key] = dict(id=key, name=name, tenant='tenant-a', states=['todo', 'doing', 'done'],
                                               edges=[['todo', 'doing'], ['doing', 'done']])
            if 'legacy_issues' in tables:
                for key, project, title, status in db.execute('SELECT id,project_id,title,status FROM legacy_issues'):
                    state['issues'][str(key)] = dict(id=str(key), project_id=project, title=title, status=status, version=1, tenant='tenant-a')
            db.execute('INSERT OR REPLACE INTO calibration_state VALUES(1,?)', (json.dumps(state),))
            db.execute('PRAGMA user_version=2')

    def request(self, method, url, body, token):
        parsed = urlsplit(url)
        if method == 'GET' and parsed.path == '/api/health':
            return 200, dict(ok=True, schema=2)
        try:
            with sqlite3.connect(self.db, timeout=10) as db:
                db.execute('BEGIN IMMEDIATE')
                state = json.loads(db.execute('SELECT payload FROM calibration_state WHERE id=1').fetchone()[0])
                require(token in state['roles'], 401, 'unauthorized')
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
        def get(collection, key):
            item = s[collection].get(key)
            require(item is not None and item['tenant'] == tenant, 404, 'not_found')
            return item

        def audit(action, rid):
            s['audit'].append(dict(actor=token, action=action, resource_id=rid, tenant=tenant))

        def validate(item, version, changes):
            require(FAULT == 'ignore_version' or item['version'] == version, 409, 'version_conflict')
            if 'title' in changes:
                require(isinstance(changes['title'], str) and 1 <= len(changes['title']) <= 200)
            if 'status' in changes:
                project = get('projects', item['project_id'])
                require([item['status'], changes['status']] in project['edges'], 409, 'workflow_conflict')

        def apply(item, changes, action='update'):
            for key in ('title', 'status'):
                if key in changes:
                    item[key] = changes[key]
            item['version'] += 1
            audit(action, item['id'])

        if method == 'PATCH' and path == '/api/members/member-a':
            require(s['roles'][token] == 'admin', 403, 'forbidden')
            s['roles']['member-a'] = body['role']
            return 200, dict(role=body['role'])
        if method == 'POST' and path == '/api/projects':
            item = dict(id=uid(), name=body['name'], tenant=tenant, states=['todo', 'doing', 'done'],
                        edges=[['todo', 'doing'], ['doing', 'done']])
            s['projects'][item['id']] = item
            audit('project_create', item['id'])
            return 201, item
        if method == 'GET' and path == '/api/projects':
            return 200, dict(items=[i for i in s['projects'].values() if i['tenant'] == tenant])
        if method == 'PATCH' and path.startswith('/api/projects/') and path.endswith('/workflow'):
            item = get('projects', path.split('/')[3])
            require(all(i['status'] in body['states'] for i in s['issues'].values() if i['project_id'] == item['id']), 409, 'state_in_use')
            require(all(a in body['states'] and b in body['states'] for a, b in body['edges']))
            item.update(states=body['states'], edges=body['edges'])
            audit('workflow', item['id'])
            return 200, item
        if method == 'POST' and path == '/api/issues':
            get('projects', body['project_id'])
            require(isinstance(body['title'], str) and 1 <= len(body['title']) <= 200)
            item = dict(id=uid(), project_id=body['project_id'], title=body['title'], status='todo', version=1, tenant=tenant)
            s['issues'][item['id']] = item
            audit('issue_create', item['id'])
            return 201, item
        if method == 'GET' and path in ('/api/issues', '/api/issues/export'):
            rows = [dict(i) for i in s['issues'].values() if i['tenant'] == tenant]
            for field in ('project_id', 'status', 'q'):
                if field in query:
                    rows = [i for i in rows if (query[field][0] in i['title'] if field == 'q' else i[field] == query[field][0])]
            rows.sort(key=lambda i: i['id'])
            if path.endswith('/export'):
                return 200, dict(items=rows)
            start, limit = int(query.get('cursor', ['0'])[0]), int(query.get('limit', ['100'])[0])
            return 200, dict(items=rows[start:start+limit], next_cursor=str(start+limit) if start+limit < len(rows) else None)
        if path.startswith('/api/issues/'):
            item = get('issues', path.split('/')[3])
            if path.endswith('/comments'):
                if method == 'POST':
                    comment = dict(id=uid(), text=body['text'], author=token)
                    s['comments'].setdefault(item['id'], []).append(comment)
                    audit('comment', item['id'])
                    return 201, comment
                if method == 'GET':
                    return 200, dict(items=s['comments'].get(item['id'], []))
            if method == 'GET':
                return 200, item
            if method == 'PATCH':
                validate(item, body['version'], body)
                apply(item, body)
                return 200, item
        if method == 'POST' and path == '/api/batches':
            entries = []
            for operation in body['operations']:
                item = get('issues', operation['id'])
                try:
                    validate(item, operation['version'], operation['changes'])
                except Rejected as error:
                    if FAULT == 'partial_batch':
                        return error.status, error.body
                    raise
                entries.append(dict(id=item['id'], before={k: item[k] for k in operation['changes']},
                                    after_version=item['version'] + 1, changes=operation['changes']))
                if FAULT == 'partial_batch':
                    apply(item, operation['changes'], 'batch_update')
            if FAULT != 'partial_batch':
                for entry in entries:
                    apply(get('issues', entry['id']), entry['changes'], 'batch_update')
            batch = dict(id=uid(), tenant=tenant, entries=entries)
            s['batches'][batch['id']] = batch
            return 201, dict(id=batch['id'])
        if method == 'POST' and path.startswith('/api/batches/') and path.endswith('/undo'):
            batch = get('batches', path.split('/')[3])
            for entry in batch['entries']:
                require(get('issues', entry['id'])['version'] == entry['after_version'], 409, 'undo_conflict')
            for entry in batch['entries']:
                apply(get('issues', entry['id']), entry['before'], 'undo')
            return 200, dict(id=batch['id'])
        if method == 'GET' and path == '/api/audit':
            return 200, dict(items=[i for i in s['audit'] if i['tenant'] == tenant])
        return 404, dict(error='not_found')
