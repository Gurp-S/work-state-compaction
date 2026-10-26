"""Author-only transactional booking protocol calibration; no complete UI."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, parse_qs
import uuid

FAULT = 'none'


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.body = status, {'error': code}


def require(ok, status=400, code='invalid_request'):
    if not ok:
        raise Rejected(status, code)


def instant(value):
    try:
        result = datetime.fromisoformat(value)
        require(result.utcoffset() is not None)
        return result
    except (ValueError, TypeError):
        raise Rejected(400, 'invalid_time')


def uid():
    return uuid.uuid4().hex


class Service:
    def __init__(self, root, fault_hook=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'booking.sqlite3'
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS calibration_state(id INTEGER PRIMARY KEY,payload TEXT)')
            if not db.execute('SELECT 1 FROM calibration_state WHERE id=1').fetchone():
                state = dict(resources={'room-a': dict(id='room-a', tenant='tenant-a', name='room-a', timezone='UTC', version=1)},
                    bookings={}, series={}, requests={}, messages={}, deliveries=[], fail_next=0,
                    roles={'admin-a': 'admin', 'member-a': 'member', 'viewer-a': 'viewer', 'admin-b': 'admin'})
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                old = db.execute('SELECT id,payload FROM records').fetchall() if 'records' in tables else [('welcome', json.dumps(
                    dict(resource_id='room-a', start='2026-10-22T02:00:00Z', end='2026-10-22T03:00:00Z', state='confirmed')))]
                for key, payload in old:
                    state['bookings'][key] = dict(json.loads(payload), id=key, tenant='tenant-a', version=1)
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
            return 400, {'error': 'invalid_request'}

    def route(self, s, method, path, query, body, token, tenant):
        def get(collection, key):
            result = s[collection].get(key)
            require(result is not None and result['tenant'] == tenant, 404, 'not_found')
            return result

        def cached(kind):
            key = '|'.join([tenant, token, kind, body['idempotency_key']])
            fingerprint = sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            old = s['requests'].get(key)
            if old:
                require(old['fingerprint'] == fingerprint, 409, 'idempotency_conflict')
                return key, fingerprint, (200, old['response'])
            return key, fingerprint, None

        def valid_slot(rid, start, end, exclude=None, pending=()):
            get('resources', rid)
            a, b = instant(start), instant(end)
            require(a < b)
            for item in list(s['bookings'].values()) + list(pending):
                if item['id'] != exclude and item['resource_id'] == rid and item['state'] == 'confirmed':
                    require(not (a < instant(item['end']) and instant(item['start']) < b), 409, 'slot_conflict')

        def schedule(item):
            mid = item['id'] + ':' + str(item['version'])
            s['messages'][mid] = dict(message_id=mid, booking_id=item['id'], booking_version=item['version'],
                tenant=tenant, due_at=(instant(item['start']) - timedelta(hours=1)).isoformat())

        def create(rid, start, end, **extra):
            item = dict(id=uid(), resource_id=rid, start=start, end=end, tenant=tenant, state='confirmed', version=1, **extra)
            s['bookings'][item['id']] = item
            schedule(item)
            return item

        if method == 'PATCH' and path == '/api/members/member-a':
            require(s['roles'][token] == 'admin', 403, 'forbidden')
            s['roles']['member-a'] = body['role']
            return 200, dict(role=body['role'])
        if method == 'POST' and path == '/api/resources':
            item = dict(id=uid(), name=body['name'], timezone=body['timezone'], version=1, tenant=tenant)
            s['resources'][item['id']] = item
            return 201, item
        if path.startswith('/api/resources/') and method == 'PATCH':
            item = get('resources', path.split('/')[3])
            require(item['version'] == body['version'], 409, 'version_conflict')
            item.update(timezone=body['timezone'], version=item['version'] + 1)
            return 200, item
        if method == 'POST' and path == '/api/bookings':
            key, fingerprint, old = cached('booking')
            if old:
                return old
            valid_slot(body['resource_id'], body['start'], body['end'])
            item = create(body['resource_id'], body['start'], body['end'])
            s['requests'][key] = dict(fingerprint=fingerprint, response=dict(item))
            return 201, item
        if method == 'GET' and path == '/api/bookings':
            rows = [i for i in s['bookings'].values() if i['tenant'] == tenant]
            if 'resource_id' in query:
                rows = [i for i in rows if i['resource_id'] == query['resource_id'][0]]
            rows.sort(key=lambda i: i['id'])
            return 200, dict(items=rows, next_cursor=None)
        if path.startswith('/api/bookings/'):
            item = get('bookings', path.split('/')[3])
            if method == 'GET':
                return 200, item
            if method == 'POST' and path.endswith('/cancel'):
                if item['state'] == 'cancelled':
                    return 200, item
                require(item['version'] == body['version'], 409, 'version_conflict')
                item.update(state='cancelled', version=item['version'] + 1)
                return 200, item
            if method == 'PATCH':
                require(item['version'] == body['version'], 409, 'version_conflict')
                valid_slot(item['resource_id'], body['start'], body['end'], exclude=item['id'])
                item.update(start=body['start'], end=body['end'], version=item['version'] + 1)
                schedule(item)
                return 200, item
        if method == 'POST' and path == '/api/series':
            key, fingerprint, old = cached('series')
            if old:
                return old
            pending = []
            for start in body['starts']:
                end = (instant(start) + timedelta(minutes=body['duration_minutes'])).isoformat()
                valid_slot(body['resource_id'], start, end, pending=pending)
                pending.append(dict(id=uid(), resource_id=body['resource_id'], start=start, end=end, state='confirmed'))
            sid = uid()
            items = [create(i['resource_id'], i['start'], i['end'], series_id=sid, index=index) for index, i in enumerate(pending)]
            series = dict(id=sid, items=items, tenant=tenant)
            s['series'][sid] = series
            s['requests'][key] = dict(fingerprint=fingerprint, response=series)
            return 201, series
        if method == 'POST' and path.startswith('/api/series/') and path.endswith('/cancel'):
            series = get('series', path.split('/')[3])
            for saved in series['items']:
                item = get('bookings', saved['id'])
                if item['index'] >= body['from_index'] and item['state'] != 'cancelled':
                    item.update(state='cancelled', version=item['version'] + 1)
            return 200, dict(id=series['id'])
        if path == '/api/notifications/test-sink' and method == 'POST':
            s['fail_next'] = body['fail_next']
            return 200, dict(ok=True)
        if path == '/api/notifications/deliveries' and method == 'GET':
            return 200, dict(items=[i for i in s['deliveries'] if i['tenant'] == tenant])
        if path == '/api/notifications/dispatch' and method == 'POST':
            now = instant(body['now'])
            for msg in s['messages'].values():
                item = s['bookings'][msg['booking_id']]
                if msg['tenant'] != tenant or instant(msg['due_at']) > now:
                    continue
                if FAULT != 'stale_notification' and (item['state'] != 'confirmed' or item['version'] != msg['booking_version']):
                    continue
                if FAULT != 'duplicate_delivery' and any(i['message_id'] == msg['message_id'] for i in s['deliveries']):
                    continue
                if s['fail_next']:
                    s['fail_next'] -= 1
                    continue
                s['deliveries'].append(dict(msg))
            return 200, dict(ok=True)
        return 404, dict(error='not_found')
