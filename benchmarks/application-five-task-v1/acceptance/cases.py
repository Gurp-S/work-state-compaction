"""Representative public checks; manual and wider edge coverage remain required."""
import base64
from decimal import Decimal
from hashlib import sha256
import sqlite3

CASES = {}


def case(task, name, stage):
    def register(function):
        CASES.setdefault(task, []).append((name, stage, function))
        return function
    return register


def object_id(body):
    assert isinstance(body.get('id'), str) and body['id'], 'stable_string_id_missing'
    return body['id']


def health(app):
    assert app.call('GET', '/api/health', token=None)['ok'] is True
    assert '<html' in app.call('GET', '/', token=None, raw=True).lower()


for task in ('collaboration', 'files', 'imports', 'booking'):
    case(task, 'startup_and_page', 1)(health)


def new_issue(app, title='第一条工单'):
    project = app.call('POST', '/api/projects', {'name': '验收项目'}, status=201)
    pid = object_id(project)
    issue = app.call('POST', '/api/issues', {'project_id': pid, 'title': title}, status=201)
    assert issue['version'] == 1 and issue['status'] == 'todo'
    return pid, issue


@case('collaboration', 'version_conflict_and_isolation', 4)
def collaboration_conflict(app):
    pid, issue = new_issue(app)
    path = '/api/issues/' + object_id(issue)
    app.call('GET', path, token='admin-b', status=404)
    app.call('GET', path, token=None, status=401)
    results = app.race('PATCH', path, [{'version': 1, 'title': title} for title in ('修改甲', '修改乙')])
    assert sorted(r['status'] for r in results) == [200, 409], results
    winner = next(r for r in results if r['status'] == 200)
    saved = app.call('GET', path)
    assert saved['title'] == winner['request']['title'] and saved['version'] == 2
    app.restart()
    assert app.call('GET', path) == saved


@case('collaboration', 'batch_atomicity_and_undo_conflict', 5)
def collaboration_batch(app):
    pid, first = new_issue(app, '原题甲')
    second = app.call('POST', '/api/issues', {'project_id': pid, 'title': '原题乙'}, status=201)
    a, b = object_id(first), object_id(second)
    ops = [{'id': a, 'version': 1, 'changes': {'title': '新甲'}},
           {'id': b, 'version': 999, 'changes': {'title': '新乙'}}]
    app.call('POST', '/api/batches', {'operations': ops}, status=409)
    assert app.call('GET', '/api/issues/' + a)['title'] == '原题甲'
    ops[1]['version'] = 1
    batch = app.call('POST', '/api/batches', {'operations': ops}, status=201)
    app.call('PATCH', '/api/issues/' + b, {'version': 2, 'title': '第三人修改'})
    app.call('POST', '/api/batches/' + object_id(batch) + '/undo', {}, status=409)
    assert app.call('GET', '/api/issues/' + a)['title'] == '新甲'
    assert app.call('GET', '/api/issues/' + b)['title'] == '第三人修改'


@case('collaboration', 'role_change_survives_restart', 6)
def collaboration_role(app):
    _, issue = new_issue(app)
    app.call('PATCH', '/api/members/member-a', {'role': 'viewer'})
    app.restart()
    app.call('PATCH', '/api/issues/' + object_id(issue), {'version': 1, 'title': '越权'}, token='member-a', status=403)
    assert app.call('GET', '/api/issues/' + issue['id'])['title'] == issue['title']


@case('collaboration', 'legacy_migration_twice', 8)
def collaboration_legacy(app):
    issue = app.call('GET', '/api/issues/7')
    assert issue['title'] == '原始证据标题' and issue['version'] == 1
    app.call('PATCH', '/api/issues/7', {'version': 1, 'title': '迁移后修改'})
    app.restart()
    assert app.call('GET', '/api/issues/7')['version'] == 2


def seed_legacy(app):
    """Create authentic v1 data before the first application startup."""
    with sqlite3.connect(app.data / 'teamflow.sqlite3') as db:
        db.executescript('CREATE TABLE IF NOT EXISTS legacy_projects(id TEXT PRIMARY KEY,name TEXT NOT NULL);'
                         'CREATE TABLE IF NOT EXISTS legacy_issues(id INTEGER PRIMARY KEY,project_id TEXT,title TEXT,status TEXT);')
        db.execute('INSERT OR REPLACE INTO legacy_projects VALUES(?,?)', ('welcome', 'Welcome'))
        db.execute('INSERT OR REPLACE INTO legacy_issues VALUES(?,?,?,?)', (7, 'welcome', '原始证据标题', 'todo'))
        db.execute('PRAGMA user_version=1')


def begin_upload(app, data=b'hello\x00world', name='test.bin'):
    body = {'name': name, 'folder': '/', 'size': len(data), 'sha256': sha256(data).hexdigest()}
    item = app.call('POST', '/api/uploads', body, status=201)
    assert item['offset'] == 0
    return '/api/uploads/' + object_id(item), data


def upload(app, data=b'hello\x00world'):
    path, data = begin_upload(app, data)
    app.call('PATCH', path, {'offset': 0, 'data_b64': base64.b64encode(data).decode()})
    result = app.call('POST', path + '/complete', {}, status=201)
    assert result['sha256'] == sha256(data).hexdigest() and result['size'] == len(data)
    return result


@case('files', 'resume_and_chunk_identity', 2)
def file_resume(app):
    path, data = begin_upload(app)
    part = {'offset': 0, 'data_b64': base64.b64encode(data[:5]).decode()}
    assert app.call('PATCH', path, part)['offset'] == 5
    app.restart()
    assert app.call('GET', path)['offset'] == 5
    assert app.call('PATCH', path, part)['offset'] == 5
    app.call('PATCH', path, {'offset': 0, 'data_b64': 'eHh4eHg='}, status=409)
    app.call('PATCH', path, {'offset': 5, 'data_b64': base64.b64encode(data[5:]).decode()})
    item = app.call('POST', path + '/complete', {}, status=201)
    assert app.call('POST', path + '/complete', {})['id'] == item['id']
    received = app.call('GET', '/api/files/' + object_id(item) + '/content')['data_b64']
    assert base64.b64decode(received, validate=True) == data


@case('files', 'deleted_file_rejects_late_write', 5)
def file_delete(app):
    item = upload(app)
    path = '/api/files/' + object_id(item)
    deleted = app.call('DELETE', path + '?version=1')
    app.call('GET', path, status=404)
    app.call('PATCH', path, {'version': 1, 'name': 'late.bin'}, status=404)
    app.restart()
    app.call('GET', path, status=404)
    restored = app.call('POST', path + '/restore', {'version': deleted['version']})
    assert restored['version'] > deleted['version']
    app.call('PATCH', path, {'version': 1, 'name': 'late.bin'}, status=409)
    assert app.call('GET', path)['name'] == item['name']


@case('files', 'share_revocation_and_live_content_gc', 7)
def file_share(app):
    item = upload(app)
    share = app.call('POST', '/api/shares', {'file_id': object_id(item)}, status=201)
    token = share['token']
    assert base64.b64decode(app.call('GET', '/api/shared/' + token, token=None)['data_b64']) == b'hello\x00world'
    app.call('DELETE', '/api/shares/' + token)
    app.restart()
    app.call('GET', '/api/shared/' + token, token=None, status=404)
    app.call('POST', '/api/maintenance/gc', {})
    assert base64.b64decode(app.call('GET', '/api/files/' + item['id'] + '/content')['data_b64']) == b'hello\x00world'
    app.call('GET', '/api/files/' + item['id'] + '/content', token='admin-b', status=404)


def batch_body(key='batch-one', data=b'customer,amount\nAlice,0.10\nBob,0.20\nUnknown,\n'):
    return {'idempotency_key': key, 'format': 'csv', 'data_b64': base64.b64encode(data).decode(),
            'mapping': {'customer': 'customer', 'amount': 'amount'}, 'duplicate_policy': 'append'}


@case('imports', 'strict_utf8_and_preview_no_commit', 2)
def import_strict(app):
    body = batch_body()
    preview = app.call('POST', '/api/imports/preview', body)
    assert preview['valid'] is True and len(preview['rows']) == 3
    before = app.call('GET', '/api/records')['items']
    body['data_b64'] = base64.b64encode(b'customer,amount\nbad\xff,1\n').decode()
    preview = app.call('POST', '/api/imports/preview', body)
    assert preview['valid'] is False and preview['errors'], preview
    assert app.call('GET', '/api/records')['items'] == before


@case('imports', 'idempotency_decimal_and_lineage', 7)
def import_idempotent(app):
    body = batch_body()
    batch = app.call('POST', '/api/batches', body, status=201)
    bid = object_id(batch)
    assert app.call('POST', '/api/batches', body)['id'] == bid
    changed = dict(body, duplicate_policy='reject')
    app.call('POST', '/api/batches', changed, status=409)
    assert app.call('POST', '/api/batches/' + bid + '/run', {})['state'] == 'committed'
    app.restart()
    app.call('POST', '/api/batches/' + bid + '/run', {})
    rows = [r for r in app.call('GET', '/api/records')['items'] if r.get('batch_id') == bid]
    assert len(rows) == 3 and {r['source_line'] for r in rows} == {2, 3, 4}
    assert base64.b64decode(app.call('GET', '/api/batches/' + bid + '/source')['data_b64']) == base64.b64decode(body['data_b64'])
    report = app.call('GET', '/api/report')
    assert Decimal(report['known_sum']) == Decimal('0.30') and report['known_count'] == 2
    assert report['unknown_count'] >= 1 and report['total_count'] == report['known_count'] + report['unknown_count']
    assert {r['id'] for r in app.call('GET', '/api/records/export?q=Alice')['items']} == {r['id'] for r in rows if r['customer'] == 'Alice'}


@case('imports', 'cancel_survives_restart', 5)
def import_cancel(app):
    batch = app.call('POST', '/api/batches', batch_body(), status=201)
    path = '/api/batches/' + object_id(batch)
    before = app.call('GET', '/api/records')['items']
    app.call('POST', path + '/cancel', {})
    app.restart()
    app.call('POST', path + '/run', {}, status=409)
    assert app.call('GET', path)['state'] == 'cancelled'
    assert app.call('GET', '/api/records')['items'] == before


def resource(app):
    return object_id(app.call('POST', '/api/resources', {'name': '会议室', 'timezone': 'UTC'}, status=201))


def reservation(rid, key='one', start='2026-11-01T10:00:00Z', end='2026-11-01T11:00:00Z'):
    return dict(resource_id=rid, idempotency_key=key, start=start, end=end)


@case('booking', 'concurrent_slot_and_idempotency', 3)
def booking_race(app):
    rid = resource(app)
    bodies = [reservation(rid, key) for key in ('one', 'two')]
    results = app.race('POST', '/api/bookings', bodies)
    assert sorted(r['status'] for r in results) == [201, 409], results
    win = next(r for r in results if r['status'] == 201)
    app.restart()
    assert app.call('POST', '/api/bookings', win['request'])['id'] == object_id(win['body'])
    app.call('POST', '/api/bookings', dict(win['request'], end='2026-11-01T12:00:00Z'), status=409)
    app.call('POST', '/api/bookings', reservation(rid, 'adjacent', '2026-11-01T11:00:00Z', '2026-11-01T12:00:00Z'), status=201)


@case('booking', 'timezone_preserves_promised_instant', 2)
def booking_timezone(app):
    from datetime import datetime
    rid = resource(app)
    item = app.call('POST', '/api/bookings', reservation(rid), status=201)
    app.call('PATCH', '/api/resources/' + rid, {'version': 1, 'timezone': 'Asia/Shanghai'})
    saved = app.call('GET', '/api/bookings/' + object_id(item))
    assert datetime.fromisoformat(saved['start']) == datetime.fromisoformat(item['start'])
    app.call('POST', '/api/bookings', reservation(rid, 'same-instant', '2026-11-01T18:00:00+08:00', '2026-11-01T19:00:00+08:00'), status=409)


@case('booking', 'cancel_invalidates_old_notification', 6)
def booking_cancel(app):
    rid = resource(app)
    item = app.call('POST', '/api/bookings', reservation(rid), status=201)
    path = '/api/bookings/' + object_id(item)
    app.call('POST', path + '/cancel', {'version': 1})
    app.restart()
    app.call('POST', '/api/notifications/dispatch', {'now': '2026-11-01T12:00:00Z'})
    deliveries = app.call('GET', '/api/notifications/deliveries')['items']
    assert not [d for d in deliveries if d['booking_id'] == item['id']]
    assert app.call('GET', path)['state'] == 'cancelled'
    app.call('POST', '/api/bookings', reservation(rid, 'replacement'), status=201)
