"""Public checks for stage changes, historical evidence and final recovery."""
import base64
from decimal import Decimal

from cases import case, new_issue, object_id, upload, begin_upload, batch_body, resource, reservation


@case('collaboration', 'workflow_comments_and_successful_undo', 5)
def collaboration_workflow(app):
    pid, issue = new_issue(app)
    path = '/api/issues/' + object_id(issue)
    app.call('PATCH', '/api/projects/' + pid + '/workflow',
             {'states': ['todo', 'review', 'done'], 'edges': [['todo', 'review'], ['review', 'done']]})
    app.call('PATCH', path, {'version': 1, 'status': 'done'}, status=409)
    app.call('POST', path + '/comments', {'text': '保留原始证据'}, token='member-a', status=201)
    app.call('PATCH', path, {'version': 1, 'status': 'review'})
    current = app.call('GET', path)
    batch = app.call('POST', '/api/batches', {'operations': [
        {'id': issue['id'], 'version': current['version'], 'changes': {'title': '临时标题'}}]}, status=201)
    changed = app.call('GET', path)
    app.call('POST', '/api/batches/' + object_id(batch) + '/undo', {})
    restored = app.call('GET', path)
    assert restored['title'] == issue['title'] and restored['version'] > changed['version']
    app.restart()
    assert any(c['text'] == '保留原始证据' for c in app.call('GET', path + '/comments')['items'])
    audit = app.call('GET', '/api/audit')['items']
    assert any(e.get('actor') and e.get('action') and e.get('resource_id') == issue['id'] for e in audit)


@case('files', 'history_gc_and_permanent_delete', 7)
def files_history(app):
    first = upload(app, b'original bytes')
    path = '/api/files/' + object_id(first)
    from hashlib import sha256
    content = b'replacement bytes'
    second = app.call('POST', path + '/versions', {'version': 1,
        'data_b64': base64.b64encode(content).decode(), 'sha256': sha256(content).hexdigest()}, status=201)
    assert second['version'] == 2
    app.call('POST', '/api/maintenance/gc', {})
    app.restart()
    assert base64.b64decode(app.call('GET', path + '/content?version=1')['data_b64'], validate=True) == b'original bytes'
    assert base64.b64decode(app.call('GET', path + '/content')['data_b64'], validate=True) == content
    removed = app.call('DELETE', path + '?version=2')
    app.call('DELETE', '/api/trash/' + first['id'] + '?version=' + str(removed['version']))
    app.restart()
    app.call('POST', path + '/restore', {'version': removed['version']}, status=404)


@case('files', 'hash_failure_does_not_publish', 3)
def files_hash(app):
    path, _ = begin_upload(app, b'original')
    before = app.call('GET', '/api/files')['items']
    app.call('PATCH', path, {'offset': 0, 'data_b64': base64.b64encode(b'changed!').decode()})
    app.call('POST', path + '/complete', {}, status=422)
    assert app.call('GET', '/api/files')['items'] == before
    app.call('POST', '/api/uploads', {'name': '../escape', 'folder': '/', 'size': 0, 'sha256': '0' * 64}, status=400)


@case('imports', 'physical_line_errors_and_duplicate_keys', 2)
def imports_errors(app):
    body = batch_body(data=b'customer,amount\n"two\nlines",0.10\nbroken,NaN\n')
    preview = app.call('POST', '/api/imports/preview', body)
    assert preview['valid'] is False
    assert any(e['line'] == 4 and e['code'] for e in preview['errors']), preview
    body = batch_body(data=b'{"customer":"first","customer":"second","amount":"1"}\n')
    body['format'] = 'jsonl'
    preview = app.call('POST', '/api/imports/preview', body)
    assert preview['valid'] is False and preview['errors'][0]['line'] == 1
    body = batch_body(data='\ufeffcustomer,amount\n合法客户,0\n'.encode())
    preview = app.call('POST', '/api/imports/preview', body)
    assert preview['valid'] and preview['rows'][0]['customer'] == '合法客户'


@case('imports', 'duplicate_batch_rolls_back_all_rows', 3)
def imports_duplicate(app):
    before = app.call('GET', '/api/records')['items']
    body = batch_body(data=b'customer,amount\nUnique,1\nDuplicate,2\nDuplicate,3\n')
    body['duplicate_policy'] = 'reject'
    batch = app.call('POST', '/api/batches', body, status=201)
    failed = app.call('POST', '/api/batches/' + object_id(batch) + '/run', {})
    assert failed['state'] == 'failed' and failed['errors']
    app.restart()
    assert app.call('GET', '/api/records')['items'] == before


@case('imports', 'schema_change_keeps_queued_mapping', 4)
def imports_schema(app):
    old = app.call('POST', '/api/batches', batch_body('old', b'customer,amount\nOld,1.25\n'), status=201)
    body = batch_body('new', b'client_name,amount_cny\nNew,\n')
    body.update(schema_version=2, mapping={'customer': 'client_name', 'amount': 'amount_cny'})
    new = app.call('POST', '/api/batches', body, status=201)
    app.restart()
    for item in (new, old):
        assert app.call('POST', '/api/batches/' + object_id(item) + '/run', {})['state'] == 'committed'
    first = app.call('GET', '/api/records/export?schema_version=1')['items']
    second = app.call('GET', '/api/records/export?schema_version=2')['items']
    assert {r['id']: (r['customer'], r['amount']) for r in first} == {
        r['id']: (r['client_name'], r['amount_cny']) for r in second}
    assert next(r for r in first if r['customer'] == 'New')['amount'] is None
    assert Decimal(next(r for r in first if r['customer'] == 'Old')['amount']) == Decimal('1.25')


@case('imports', 'concurrent_run_commits_once', 5)
def imports_concurrent(app):
    batch = app.call('POST', '/api/batches', batch_body(), status=201)
    bid = object_id(batch)
    results = app.race('POST', '/api/batches/' + bid + '/run', [{}, {}])
    # An implementation may reject an in-flight competitor; final data is decisive.
    assert all(r['status'] in (200, 409) for r in results) and any(r['status'] == 200 for r in results)
    app.restart()
    assert len([r for r in app.call('GET', '/api/records')['items'] if r.get('batch_id') == bid]) == 3


@case('imports', 'unknown_zero_isolation_and_legacy', 8)
def imports_unknown(app):
    initial = app.call('GET', '/api/records')['items']
    legacy = next(r for r in initial if r['id'] == 'welcome')
    assert legacy['customer'] == 'Legacy' and legacy['amount'] is None and legacy['source_line'] is None
    for key, raw in [('unknown', b'customer,amount\nOnlyUnknown,\n'), ('zero', b'customer,amount\nOnlyZero,0\n')]:
        item = app.call('POST', '/api/batches', batch_body(key, raw), status=201)
        app.call('POST', '/api/batches/' + object_id(item) + '/run', {})
        app.call('GET', '/api/batches/' + item['id'] + '/source', token='admin-b', status=404)
    unknown = app.call('GET', '/api/report?q=OnlyUnknown')
    zero = app.call('GET', '/api/report?q=OnlyZero')
    fields = ('known_sum', 'known_count', 'unknown_count', 'total_count')
    assert {key: unknown[key] for key in fields} == dict(known_sum=None, known_count=0, unknown_count=1, total_count=1)
    assert {key: zero[key] for key in fields} == dict(known_sum='0', known_count=1, unknown_count=0, total_count=1)
    app.call('POST', '/api/batches', batch_body('forbidden'), token='viewer-a', status=403)
    app.restart()
    assert next(r for r in app.call('GET', '/api/records')['items'] if r['id'] == 'welcome') == legacy


@case('booking', 'series_conflict_is_atomic', 4)
def booking_series(app):
    rid = resource(app)
    app.call('POST', '/api/bookings', reservation(rid), status=201)
    before = app.call('GET', '/api/bookings?resource_id=' + rid)['items']
    body = dict(resource_id=rid, starts=['2026-11-01T08:00:00Z', '2026-11-01T10:00:00Z'],
                duration_minutes=60, idempotency_key='series')
    app.call('POST', '/api/series', body, status=409)
    assert app.call('GET', '/api/bookings?resource_id=' + rid)['items'] == before
    body['starts'][1] = '2026-11-02T08:00:00Z'
    series = app.call('POST', '/api/series', body, status=201)
    assert len(series['items']) == 2
    app.call('POST', '/api/series/' + object_id(series) + '/cancel', {'from_index': 1})
    assert app.call('GET', '/api/bookings/' + series['items'][0]['id'])['state'] == 'confirmed'
    assert app.call('GET', '/api/bookings/' + series['items'][1]['id'])['state'] == 'cancelled'


@case('booking', 'notification_retry_and_restart_dedup', 5)
def booking_notifications(app):
    rid = resource(app)
    item = app.call('POST', '/api/bookings', reservation(rid), status=201)
    app.call('POST', '/api/notifications/test-sink', {'fail_next': 1})
    dispatch = {'now': '2026-11-01T09:30:00Z'}
    app.call('POST', '/api/notifications/dispatch', dispatch)
    assert not [r for r in app.call('GET', '/api/notifications/deliveries')['items'] if r['booking_id'] == item['id']]
    app.restart()
    app.call('POST', '/api/notifications/dispatch', dispatch)
    app.call('POST', '/api/notifications/dispatch', dispatch)
    delivered = [r for r in app.call('GET', '/api/notifications/deliveries')['items'] if r['booking_id'] == item['id']]
    assert len(delivered) == 1 and delivered[0]['booking_version'] == 1 and delivered[0]['message_id']
