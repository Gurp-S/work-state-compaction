"""Author-only HTTP calibration backend. Never include in model task material.

This exercises import checks; it is not a complete application or a candidate.
"""
import base64
import csv
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit
import uuid

FAULT = 'none'


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.body = status, {'error': code}


def require(condition, status=400, code='invalid_request'):
    if not condition:
        raise Rejected(status, code)


def decode(raw):
    return base64.b64decode(raw, validate=True)


def preview(body):
    errors, rows = [], []
    raw = decode(body['data_b64'])
    try:
        text = raw.decode('utf-8-sig', errors='replace' if FAULT == 'replacement_decode' else 'strict')
    except UnicodeDecodeError as error:
        return dict(valid=False, rows=[], errors=[dict(line=raw[:error.start].count(b'\n') + 1, code='invalid_utf8')])
    mapping = body.get('mapping', {'customer': 'customer', 'amount': 'amount'})

    def append(item, line):
        try:
            require(isinstance(item, dict))
            customer = item.get(mapping['customer'])
            amount = item.get(mapping['amount'])
            require(isinstance(customer, str) and customer.strip())
            if amount == '' and body['format'] == 'csv':
                amount = None
            require(amount is None or isinstance(amount, str))
            if amount is not None:
                require(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', amount) is not None)
                require(Decimal(amount).is_finite())
            rows.append(dict(customer=customer, amount=amount, source_line=line))
        except (Rejected, KeyError, InvalidOperation):
            errors.append(dict(line=line, code='invalid_record'))

    if body['format'] == 'csv':
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        try:
            headers = next(reader)
            require(len(set(headers)) == len(headers))
            while True:
                line = reader.line_num + 1
                try:
                    values = next(reader)
                except StopIteration:
                    break
                if len(values) != len(headers):
                    errors.append(dict(line=line, code='column_count'))
                else:
                    append(dict(zip(headers, values)), line)
        except (StopIteration, csv.Error, Rejected):
            errors.append(dict(line=max(1, reader.line_num), code='invalid_csv'))
    elif body['format'] == 'jsonl':
        def pairs(entries):
            result = {}
            for key, value in entries:
                if key in result:
                    raise ValueError('duplicate_key')
                result[key] = value
            return result
        for line, value in enumerate(text.splitlines(), 1):
            try:
                item = json.loads(value, object_pairs_hook=pairs,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                append(item, line)
            except ValueError:
                errors.append(dict(line=line, code='invalid_json'))
    else:
        raise Rejected(400, 'invalid_format')
    return dict(valid=not errors, rows=rows, errors=errors)


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'imports.sqlite3'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.executescript('''CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,tenant TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,tenant TEXT,actor TEXT,key TEXT,fingerprint TEXT,payload TEXT,state TEXT,errors TEXT,UNIQUE(tenant,actor,key));
                CREATE TABLE IF NOT EXISTS roles(token TEXT PRIMARY KEY,role TEXT);''')
            # The same initial v1 record as the published starter.
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version < 2:
                db.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
                if version == 0:
                    db.execute('INSERT OR IGNORE INTO records VALUES(?,?)', ('welcome', json.dumps(
                        dict(customer='Legacy', amount=None, batch_id='legacy', source_line=None))))
                for row in db.execute('SELECT id,payload FROM records').fetchall():
                    db.execute('INSERT OR IGNORE INTO entries VALUES(?,?,?)', (row['id'], 'tenant-a', row['payload']))
                db.execute('PRAGMA user_version=2')
            for token, role in [('admin-a', 'admin'), ('member-a', 'member'), ('viewer-a', 'viewer'), ('admin-b', 'admin')]:
                db.execute('INSERT OR IGNORE INTO roles VALUES(?,?)', (token, role))

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def request(self, method, path, body, token):
        parsed = urlsplit(path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if method == 'GET' and path == '/api/health':
                return 200, {'ok': True, 'schema': 2}
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                identity = db.execute('SELECT role FROM roles WHERE token=?', (token,)).fetchone()
                require(identity is not None, 401, 'unauthorized')
                role = identity['role']
                tenant = 'tenant-b' if token == 'admin-b' else 'tenant-a'
                if method != 'GET':
                    require(role != 'viewer', 403, 'forbidden')
                if method == 'PATCH' and path == '/api/members/member-a':
                    require(role == 'admin', 403, 'forbidden')
                    db.execute('UPDATE roles SET role=? WHERE token=?', (body['role'], 'member-a'))
                    return 200, dict(role=body['role'])
                if method == 'POST' and path == '/api/imports/preview':
                    return 200, preview(body)
                if method == 'POST' and path == '/api/batches':
                    require(body.get('idempotency_key') and body.get('duplicate_policy') in ('append', 'reject'))
                    fingerprint = sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                    old = db.execute('SELECT * FROM batches WHERE tenant=? AND actor=? AND key=?',
                                     (tenant, token, body['idempotency_key'])).fetchone()
                    if old:
                        require(old['fingerprint'] == fingerprint, 409, 'idempotency_conflict')
                        return 200, dict(id=old['id'], state=old['state'])
                    bid = uuid.uuid4().hex
                    db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)',
                        (bid, tenant, token, body['idempotency_key'], fingerprint, json.dumps(body), 'queued', '[]'))
                    return 201, dict(id=bid, state='queued')
                if path.startswith('/api/batches/'):
                    parts = path.split('/')
                    batch = db.execute('SELECT * FROM batches WHERE id=? AND tenant=?', (parts[3], tenant)).fetchone()
                    require(batch is not None, 404, 'not_found')
                    state, bid, payload = batch['state'], batch['id'], json.loads(batch['payload'])
                    action = parts[4] if len(parts) == 5 else ''
                    if method == 'GET' and action == 'source':
                        return 200, dict(data_b64=payload['data_b64'])
                    if method == 'GET' and not action:
                        return 200, dict(id=bid, state=state, errors=json.loads(batch['errors']))
                    if method == 'POST' and action == 'cancel':
                        require(state in ('queued', 'cancelled'), 409, 'already_processed')
                        db.execute('UPDATE batches SET state=? WHERE id=?', ('cancelled', bid))
                        return 200, dict(id=bid, state='cancelled')
                    if method == 'POST' and action == 'run':
                        require(state != 'cancelled', 409, 'cancelled')
                        if state in ('committed', 'failed') and FAULT != 'duplicate_commit':
                            return 200, dict(id=bid, state=state, errors=json.loads(batch['errors']))
                        result = preview(payload)
                        if payload['duplicate_policy'] == 'reject':
                            seen = {json.loads(r['payload'])['customer'] for r in db.execute('SELECT payload FROM entries WHERE tenant=?', (tenant,))}
                            for row in result['rows']:
                                if row['customer'] in seen:
                                    result['errors'].append(dict(line=row['source_line'], code='duplicate_customer'))
                                seen.add(row['customer'])
                        state = 'failed' if result['errors'] else 'committed'
                        if state == 'committed':
                            for row in result['rows']:
                                record = dict(row, batch_id=bid)
                                db.execute('INSERT INTO entries VALUES(?,?,?)', (uuid.uuid4().hex, tenant, json.dumps(record, ensure_ascii=False)))
                        db.execute('UPDATE batches SET state=?,errors=? WHERE id=?', (state, json.dumps(result['errors']), bid))
                        return 200, dict(id=bid, state=state, errors=result['errors'])
                if method == 'GET' and path in ('/api/records', '/api/records/export', '/api/report'):
                    rows = [dict(id=r['id'], **json.loads(r['payload'])) for r in db.execute('SELECT * FROM entries WHERE tenant=? ORDER BY id', (tenant,))]
                    if FAULT == 'unknown_as_zero':
                        rows = [dict(r, amount='0') if r['amount'] is None else r for r in rows]
                    if 'q' in query:
                        rows = [r for r in rows if query['q'][0] in r['customer']]
                    if path == '/api/report':
                        known = [Decimal(r['amount']) for r in rows if r['amount'] is not None]
                        total = sum(known, Decimal(0))
                        return 200, dict(known_sum=(format(total, 'f') if total else '0') if known else None,
                                         known_count=len(known), unknown_count=len(rows)-len(known), total_count=len(rows))
                    if path.endswith('/export') and query.get('schema_version') == ['2']:
                        rows = [dict(id=r['id'], client_name=r['customer'], amount_cny=r['amount'],
                                     batch_id=r['batch_id'], source_line=r['source_line']) for r in rows]
                    if path == '/api/records':
                        start = int(query.get('cursor', ['0'])[0])
                        limit = int(query.get('limit', ['100'])[0])
                        require(1 <= limit <= 100)
                        end = start + limit
                        return 200, dict(items=rows[start:end], next_cursor=str(end) if end < len(rows) else None)
                    return 200, dict(items=rows)
                return 404, {'error': 'not_found'}
        except Rejected as error:
            return error.status, error.body
        except (ValueError, TypeError, KeyError):
            return 400, {'error': 'invalid_request'}
