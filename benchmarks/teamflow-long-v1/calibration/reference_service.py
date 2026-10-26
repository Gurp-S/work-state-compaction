"""Author calibration implementation; never copied into candidate workspace."""
import base64
import csv
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit
import uuid


class Rejected(Exception):
    def __init__(self, status, code, **details):
        self.status, self.body = status, {'error': code, **details}


def require(ok, status=400, code='invalid_request', **details):
    if not ok:
        raise Rejected(status, code, **details)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'blobs').mkdir(exist_ok=True)
        self.db = self.root / 'teamflow.sqlite3'
        self.fault_hook = fault_hook or (lambda point: None)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            version = c.execute('PRAGMA user_version').fetchone()[0]
            schema = [
                'CREATE TABLE IF NOT EXISTS members(token TEXT PRIMARY KEY,tenant TEXT,user_id TEXT,role TEXT,active INTEGER)',
                'CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,tenant TEXT,name TEXT,mode TEXT,version INTEGER)',
                'CREATE TABLE IF NOT EXISTS issues(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,tenant TEXT,project_id TEXT,title TEXT,description TEXT,status TEXT,priority INTEGER,version INTEGER,deleted INTEGER)',
                'CREATE TABLE IF NOT EXISTS comments(id TEXT PRIMARY KEY,tenant TEXT,issue_id TEXT,text TEXT,author TEXT)',
                'CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,tenant TEXT,issue_id TEXT,name TEXT,digest TEXT,size INTEGER)',
                'CREATE TABLE IF NOT EXISTS requests(tenant TEXT,user_id TEXT,request_id TEXT,fingerprint TEXT,status INTEGER,response TEXT,PRIMARY KEY(tenant,user_id,request_id))',
                'CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,tenant TEXT,project_id TEXT,state TEXT,snapshot TEXT,lease_token TEXT,lease_until INTEGER,artifact TEXT,usage_tokens INTEGER,attempt INTEGER)',
                'CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,tenant TEXT,user_id TEXT,action TEXT,object_id TEXT)',
            ]
            for statement in schema:
                c.execute(statement)
            members = [('a-admin','a','alice','admin'),('a-editor','a','bob','editor'),
                       ('a-viewer','a','eve','viewer'),('b-admin','b','dana','admin')]
            for row in members:
                c.execute('INSERT OR IGNORE INTO members VALUES(?,?,?,?,1)', row)
            for tenant in ('a', 'b'):
                c.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?, ?,1)',
                          (tenant + '-main', tenant, 'Main', 'active'))
            if version == 1:
                for row in c.execute('SELECT * FROM legacy_projects').fetchall():
                    c.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?, ?,1)',
                              ('legacy-' + row['id'], 'a', row['name'], 'active'))
                for row in c.execute('SELECT * FROM legacy_issues').fetchall():
                    c.execute('INSERT OR IGNORE INTO issues(id,tenant,project_id,title,description,status,priority,version,deleted) VALUES(?,?,?,?,?,?,?,1,0)',
                              ('legacy-' + str(row['id']), 'a', 'legacy-' + row['project_id'], row['title'], '', row['status'], 1))
                self.fault_hook('migration_copied')
            c.execute('PRAGMA user_version=2')

    def connect(self):
        c = sqlite3.connect(self.db, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def member(self, c, token):
        row = c.execute('SELECT * FROM members WHERE token=? AND active=1', (token,)).fetchone()
        require(row is not None, 401, 'unauthorized')
        return dict(row)

    def scoped(self, c, table, object_id, member):
        require(table in ('projects', 'issues', 'jobs', 'attachments'))
        row = c.execute(f'SELECT * FROM {table} WHERE id=? AND tenant=?', (object_id, member['tenant'])).fetchone()
        require(row is not None, 404, 'not_found')
        return dict(row)

    def writable_project(self, c, project_id, member):
        row = self.scoped(c, 'projects', project_id, member)
        require(row['mode'] == 'active', 409, 'project_not_active')
        return row

    def audit(self, c, member, action, object_id):
        c.execute('INSERT INTO audit(tenant,user_id,action,object_id) VALUES(?,?,?,?)',
                  (member['tenant'], member['user_id'], action, object_id))

    def blob(self, raw):
        digest = sha256(raw).hexdigest()
        target = self.root / 'blobs' / digest
        if not target.exists():
            tmp = target.with_name(digest + '.' + uuid.uuid4().hex + '.tmp')
            with tmp.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.fault_hook('blob_staged')
            os.replace(tmp, target)
        self.fault_hook('blob_published')
        return digest

    def request(self, method, path, body, token):
        parsed = urlsplit(path)
        path, query = parsed.path, parse_qs(parsed.query)
        if method == 'GET' and path == '/api/health':
            return 200, {'ok': True, 'schema': 2}
        try:
            with self.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                member = self.member(c, token)
                if method != 'GET':
                    require(member['role'] in ('admin', 'editor'), 403, 'forbidden')
                request_id = body.get('request_id') if isinstance(body, dict) else None
                fingerprint = sha256(canonical([method, path, body]).encode()).hexdigest()
                if request_id:
                    require(isinstance(request_id, str) and len(request_id) <= 120)
                    old = c.execute('SELECT * FROM requests WHERE tenant=? AND user_id=? AND request_id=?',
                                    (member['tenant'], member['user_id'], request_id)).fetchone()
                    if old:
                        require(old['fingerprint'] == fingerprint, 409, 'idempotency_conflict')
                        return old['status'], json.loads(old['response'])
                status, response = self.dispatch(c, member, method, path, query, body)
                if request_id:
                    c.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)',
                              (member['tenant'], member['user_id'], request_id, fingerprint, status, canonical(response)))
            if method != 'GET':
                self.fault_hook('transaction_committed')
            return status, response
        except Rejected as error:
            return error.status, error.body
        except (ValueError, TypeError, KeyError, UnicodeError):
            return 400, {'error': 'invalid_request'}

    def dispatch(self, c, member, method, path, query, body):
        tenant = member['tenant']
        parts = path.strip('/').split('/')
        if method == 'GET' and path == '/api/session':
            return 200, {k: member[k] for k in ('tenant', 'user_id', 'role')}
        if method == 'GET' and path == '/api/projects':
            return 200, {'items': [dict(r) for r in c.execute('SELECT * FROM projects WHERE tenant=? ORDER BY id', (tenant,))]}
        if method == 'POST' and path == '/api/projects':
            require(member['role'] == 'admin', 403, 'forbidden')
            name = body['name']
            require(isinstance(name, str) and 0 < len(name.strip()) <= 200)
            key = uuid.uuid4().hex
            c.execute('INSERT INTO projects VALUES(?,?,?,?,1)', (key, tenant, name, 'active'))
            self.audit(c, member, 'project_created', key)
            return 201, self.scoped(c, 'projects', key, member)
        if len(parts) == 3 and parts[:2] == ['api', 'projects'] and method == 'PATCH':
            require(member['role'] == 'admin', 403, 'forbidden')
            project = self.scoped(c, 'projects', parts[2], member)
            require(body['expected_version'] == project['version'], 409, 'version_conflict', current=project)
            require(body['mode'] in ('active', 'read_only', 'archived'))
            c.execute('UPDATE projects SET mode=?,version=version+1 WHERE id=?', (body['mode'], project['id']))
            if body['mode'] != 'active':
                c.execute("UPDATE jobs SET state='cancelled',lease_token=NULL WHERE project_id=? AND state IN ('queued','running')", (project['id'],))
            self.audit(c, member, 'project_mode_changed', project['id'])
            return 200, self.scoped(c, 'projects', project['id'], member)
        if method == 'GET' and path == '/api/issues':
            project_id = query.get('project_id', [''])[0]
            self.scoped(c, 'projects', project_id, member)
            limit = int(query.get('limit', ['50'])[0])
            require(1 <= limit <= 100)
            bound = c.execute('SELECT COALESCE(MAX(seq),0) FROM issues').fetchone()[0]
            last = 0
            if 'cursor' in query:
                cursor = json.loads(base64.urlsafe_b64decode(query['cursor'][0]))
                require(cursor['tenant'] == tenant and cursor['project'] == project_id, 400, 'cursor_scope')
                bound, last = cursor['bound'], cursor['last']
                require(type(bound) is int and type(last) is int and 0 <= last <= bound)
            rows = [dict(r) for r in c.execute('SELECT * FROM issues WHERE tenant=? AND project_id=? AND deleted=0 AND seq>? AND seq<=? ORDER BY seq', (tenant, project_id, last, bound))]
            search = query.get('q', [''])[0].casefold()
            rows = [r for r in rows if search in (r['title'] + '\n' + r['description']).casefold()
                    and (not query.get('status') or r['status'] == query['status'][0])]
            selected = rows[:limit]
            cursor = None
            if len(rows) > limit:
                cursor = base64.urlsafe_b64encode(canonical({'tenant': tenant, 'project': project_id,
                    'bound': bound, 'last': selected[-1]['seq']}).encode()).decode()
            return 200, {'items': selected, 'next_cursor': cursor}
        if method == 'POST' and path == '/api/issues':
            project = self.writable_project(c, body['project_id'], member)
            title, description = body['title'], body.get('description', '')
            require(isinstance(title, str) and 0 < len(title.strip()) <= 200 and isinstance(description, str) and len(description) <= 20000)
            priority = body.get('priority', 1)
            require(type(priority) is int and 0 <= priority <= 3)
            key = uuid.uuid4().hex
            c.execute('INSERT INTO issues(id,tenant,project_id,title,description,status,priority,version,deleted) VALUES(?,?,?,?,?,?,?,?,0)',
                      (key, tenant, project['id'], title, description, 'todo', priority, 1))
            self.audit(c, member, 'issue_created', key)
            return 201, self.scoped(c, 'issues', key, member)
        if len(parts) >= 3 and parts[:2] == ['api', 'issues']:
            issue = self.scoped(c, 'issues', parts[2], member)
            if len(parts) == 3 and method == 'GET':
                require(not issue['deleted'], 404, 'not_found')
                return 200, issue
            if method != 'GET':
                self.writable_project(c, issue['project_id'], member)
            if len(parts) == 3 and method in ('PATCH', 'DELETE'):
                require(not issue['deleted'], 404, 'not_found')
                require(type(body.get('expected_version')) is int and body['expected_version'] == issue['version'],
                        409, 'version_conflict', current=issue)
                if method == 'DELETE':
                    c.execute('UPDATE issues SET deleted=1,version=version+1 WHERE id=?', (issue['id'],))
                else:
                    for field in ('title', 'description', 'status', 'priority'):
                        if field in body:
                            value = body[field]
                            valid = (isinstance(value, str) and 0 < len(value.strip()) <= 200) if field == 'title' else \
                                (isinstance(value, str) and len(value) <= 20000) if field == 'description' else \
                                value in ('todo', 'doing', 'done') if field == 'status' else type(value) is int and 0 <= value <= 3
                            require(valid)
                            c.execute(f'UPDATE issues SET {field}=? WHERE id=?', (value, issue['id']))
                    c.execute('UPDATE issues SET version=version+1 WHERE id=?', (issue['id'],))
                self.audit(c, member, 'issue_changed', issue['id'])
                return 200, self.scoped(c, 'issues', issue['id'], member)
            if len(parts) == 4 and parts[3] == 'restore' and method == 'POST':
                require(member['role'] == 'admin', 403, 'forbidden')
                require(issue['deleted'] and body['expected_version'] == issue['version'], 409, 'version_conflict')
                c.execute('UPDATE issues SET deleted=0,version=version+1 WHERE id=?', (issue['id'],))
                return 200, self.scoped(c, 'issues', issue['id'], member)
            require(not issue['deleted'], 404, 'not_found')
            if len(parts) == 4 and parts[3] == 'comments':
                if method == 'GET':
                    return 200, {'items': [dict(r) for r in c.execute('SELECT * FROM comments WHERE issue_id=? ORDER BY rowid', (issue['id'],))]}
                if method == 'POST':
                    require(isinstance(body['text'], str) and 0 < len(body['text']) <= 10000)
                    key = uuid.uuid4().hex
                    c.execute('INSERT INTO comments VALUES(?,?,?,?,?)', (key, tenant, issue['id'], body['text'], member['user_id']))
                    return 201, {'id': key, 'text': body['text'], 'author': member['user_id']}
            if len(parts) == 4 and parts[3] == 'attachments' and method == 'POST':
                name = body['name']
                require(isinstance(name, str) and name not in ('', '.', '..') and len(name) <= 120
                        and all(ch not in name for ch in '/\\:\x00'), 400, 'invalid_filename')
                raw = base64.b64decode(body['content_base64'], validate=True)
                require(len(raw) <= 262144, 413, 'attachment_too_large')
                digest = self.blob(raw)
                key = uuid.uuid4().hex
                c.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?)', (key, tenant, issue['id'], name, digest, len(raw)))
                return 201, self.scoped(c, 'attachments', key, member)
        if len(parts) == 3 and parts[:2] == ['api', 'attachments'] and method == 'GET':
            item = self.scoped(c, 'attachments', parts[2], member)
            issue = self.scoped(c, 'issues', item['issue_id'], member)
            require(not issue['deleted'], 404, 'not_found')
            raw = (self.root / 'blobs' / item['digest']).read_bytes()
            require(sha256(raw).hexdigest() == item['digest'], 409, 'artifact_corrupt')
            return 200, {**item, 'content_base64': base64.b64encode(raw).decode()}
        if method == 'POST' and path == '/api/sync':
            operations = body['operations']
            require(isinstance(operations, list) and 0 < len(operations) <= 100)
            results = []
            for operation in operations:
                require(operation['method'] in ('POST', 'PATCH', 'DELETE') and operation['path'].startswith('/api/issues'))
                op_id = operation['op_id']
                require(isinstance(op_id, str) and 0 < len(op_id) <= 120)
                fingerprint = sha256(canonical(operation).encode()).hexdigest()
                identity = 'sync:' + op_id
                prior = c.execute('SELECT * FROM requests WHERE tenant=? AND user_id=? AND request_id=?', (tenant, member['user_id'], identity)).fetchone()
                if prior:
                    require(prior['fingerprint'] == fingerprint, 409, 'idempotency_conflict')
                    results.append(json.loads(prior['response']))
                    continue
                status, response = self.dispatch(c, member, operation['method'], operation['path'], {}, operation['body'])
                entry = {'op_id': op_id, 'status': status, 'body': response}
                c.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)', (tenant, member['user_id'], identity, fingerprint, status, canonical(entry)))
                results.append(entry)
            return 200, {'results': results}
        if method == 'POST' and path == '/api/exports':
            self.writable_project(c, body['project_id'], member)
            snapshot = [dict(r) for r in c.execute('SELECT * FROM issues WHERE tenant=? AND project_id=? AND deleted=0 ORDER BY seq', (tenant, body['project_id']))]
            key = uuid.uuid4().hex
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,NULL,NULL,NULL,NULL,0)', (key, tenant, body['project_id'], 'queued', canonical(snapshot)))
            return 202, self.scoped(c, 'jobs', key, member)
        if method == 'POST' and path == '/api/worker/claim':
            require(member['role'] == 'admin', 403, 'forbidden')
            now, ttl = body['now'], body['ttl']
            require(type(now) is int and type(ttl) is int and ttl > 0)
            row = c.execute("SELECT * FROM jobs WHERE tenant=? AND (state='queued' OR (state='running' AND lease_until<=?)) ORDER BY rowid LIMIT 1", (tenant, now)).fetchone()
            if not row:
                return 200, {'job': None}
            self.writable_project(c, row['project_id'], member)
            lease = uuid.uuid4().hex
            c.execute("UPDATE jobs SET state='running',lease_token=?,lease_until=?,attempt=attempt+1 WHERE id=?", (lease, now + ttl, row['id']))
            return 200, {'job': self.scoped(c, 'jobs', row['id'], member)}
        if method == 'POST' and path == '/api/worker/finish':
            require(member['role'] == 'admin', 403, 'forbidden')
            job = self.scoped(c, 'jobs', body['job_id'], member)
            require(job['lease_token'] == body['lease_token'], 409, 'stale_lease')
            if job['state'] == 'done':
                return 200, job
            require(job['state'] == 'running' and type(body['now']) is int and body['now'] < job['lease_until'], 409, 'stale_lease')
            self.writable_project(c, job['project_id'], member)
            tokens = body.get('usage_tokens')
            require(tokens is None or type(tokens) is int and tokens >= 0)
            out = io.StringIO(newline='')
            writer = csv.writer(out, lineterminator='\n')
            writer.writerow(['id', 'title', 'status', 'version'])
            for issue in json.loads(job['snapshot']):
                title = issue['title']
                # Spreadsheet formula injection is part of the published contract.
                if title.startswith(('=', '+', '-', '@', '\t', '\r')):
                    title = "'" + title
                writer.writerow([issue['id'], title, issue['status'], issue['version']])
            digest = self.blob(out.getvalue().encode('utf8'))
            c.execute("UPDATE jobs SET state='done',artifact=?,usage_tokens=? WHERE id=?", (digest, tokens, job['id']))
            return 200, self.scoped(c, 'jobs', job['id'], member)
        if len(parts) == 3 and parts[:2] == ['api', 'jobs']:
            job = self.scoped(c, 'jobs', parts[2], member)
            if method == 'GET':
                if job['state'] == 'done':
                    raw = (self.root / 'blobs' / job['artifact']).read_bytes()
                    require(sha256(raw).hexdigest() == job['artifact'], 409, 'artifact_corrupt')
                    job['content_base64'] = base64.b64encode(raw).decode()
                return 200, job
            if method == 'DELETE':
                c.execute("UPDATE jobs SET state='cancelled',lease_token=NULL WHERE id=?", (job['id'],))
                return 200, {'id': job['id'], 'state': 'cancelled'}
        if method == 'GET' and path == '/api/usage':
            rows = c.execute("SELECT usage_tokens FROM jobs WHERE tenant=? AND artifact IS NOT NULL", (tenant,)).fetchall()
            return 200, {'known_tokens': sum(r[0] for r in rows if r[0] is not None),
                         'unknown_records': sum(r[0] is None for r in rows), 'records': len(rows)}
        if len(parts) == 4 and parts[:3] == ['api', 'admin', 'members'] and method == 'PATCH':
            require(member['role'] == 'admin', 403, 'forbidden')
            require(body['role'] in ('admin', 'editor', 'viewer') and type(body['active']) is bool)
            row = c.execute('SELECT * FROM members WHERE tenant=? AND user_id=?', (tenant, parts[3])).fetchone()
            require(row is not None, 404, 'not_found')
            require(parts[3] != member['user_id'], 409, 'self_change_rejected')
            c.execute('UPDATE members SET role=?,active=? WHERE tenant=? AND user_id=?', (body['role'], int(body['active']), tenant, parts[3]))
            self.audit(c, member, 'membership_changed', parts[3])
            return 200, {'user_id': parts[3], 'role': body['role'], 'active': body['active']}
        if method == 'GET' and path == '/api/audit':
            require(member['role'] == 'admin', 403, 'forbidden')
            return 200, {'items': [dict(r) for r in c.execute('SELECT * FROM audit WHERE tenant=? ORDER BY seq', (tenant,))]}
        if method == 'POST' and path == '/api/admin/recover':
            require(member['role'] == 'admin', 403, 'forbidden')
            # All writes and GC hold the same database writer lock.
            live = {r[0] for r in c.execute('SELECT digest FROM attachments')}
            live.update(r[0] for r in c.execute('SELECT artifact FROM jobs WHERE artifact IS NOT NULL'))
            removed = 0
            for path in (self.root / 'blobs').iterdir():
                if path.is_file() and path.name not in live:
                    path.unlink()
                    removed += 1
            return 200, {'removed': removed}
        raise Rejected(404, 'not_found')
