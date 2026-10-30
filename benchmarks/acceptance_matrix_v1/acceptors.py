"""Coordinator-side task checks; no model scorer or answer injection.

Call only on a closed run's isolated artifact copy. Candidate execution is code
execution, not a Python security boundary; the runner supplies its isolation.
"""
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import sqlite3
import sys


def load_candidate(path):
    path = Path(path).resolve()
    name = 'matrix_candidate_' + sha256(str(path).encode()+path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(condition, code):
    if not condition:
        raise AssertionError(code)


def raises(kind, call):
    try:
        call()
    except kind:
        return
    raise AssertionError('expected_' + kind.__name__)


def collect(task, cases):
    rows = []
    for identity, constraint, check in cases:
        try:
            check()
            row = dict(check_id=identity, passed=True, constraint_id=constraint)
        except Exception as error:
            row = dict(check_id=identity, passed=False, constraint_id=constraint,
                       error_type=type(error).__name__, reason=str(error)[:2000])
        rows.append(row)
    return dict(task=task, success=all(r['passed'] for r in rows), checks=rows,
                constraint_violations=sorted({r['constraint_id'] for r in rows
                    if not r['passed'] and r['constraint_id'] is not None}),
                scope='Programmatic fixture contract only; no model, visual, or general code-quality score.')


def accept_t1(module):
    run = module.run_batch
    def job(identity='one', tenant='a', method='GET'):
        value = dict(id=identity, tenant=tenant, method=method, payload={'amount': 7})
        if method == 'POST':
            value['idempotency_key'] = tenant + '/' + identity
        return value

    def retries():
        seen = []
        def send(value, attempt):
            seen.append(attempt)
            return {'status': [429, 503, 200][len(seen)-1], 'value': 'done'}
        rows = run([job()], send)
        require(seen == [1, 2, 3] and rows == [dict(tenant='a', id='one', state='ok',
            status=200, value='done', attempts=3)], 'retry_schedule_or_result_changed')

    def terminal_500():
        seen = []
        def send(value, attempt):
            seen.append(attempt)
            return {'status': 500, 'value': 'server failure'}
        rows = run([job()], send)
        require(seen == [1] and rows[0]['state'] == 'failed' and rows[0]['status'] == 500,
                'ordinary_500_retried_or_reported_success')

    def statuses():
        for status in (200, 201, 202, 204):
            rows = run([job()], lambda value, attempt: {'status': status, 'value': None})
            require(rows == [dict(tenant='a', id='one', state='ok', status=status, value=None, attempts=1)],
                    'success_status_contract_changed')

    def total_limit():
        for limit in (1, 2, 3):
            seen = []
            def send(value, attempt):
                seen.append(attempt)
                return {'status': 503}
            rows = run([job()], send, max_attempts=limit)
            require(seen == list(range(1, limit+1)) and rows[0]['attempts'] == limit
                    and rows[0]['state'] == 'failed', 'attempt_limit_is_not_total_attempts')

    def timeout_and_immutability():
        original = job(method='POST')
        before = deepcopy(original)
        seen = []
        def send(value, attempt):
            seen.append(deepcopy(value))
            value['payload']['amount'] = 999
            if attempt == 1:
                raise TimeoutError('temporary')
            return {'status': 201, 'value': 'committed'}
        rows = run([original], send)
        require(original == before and seen == [before, before], 'request_mutated_between_attempts')
        require(rows[0]['attempts'] == 2 and rows[0]['state'] == 'ok', 'timeout_not_retried')

    def timeout_exhaustion():
        seen = []
        def send(value, attempt):
            seen.append(attempt)
            raise TimeoutError('temporary')
        rows = run([job()], send, max_attempts=2)
        require(seen == [1, 2] and rows == [dict(tenant='a', id='one', state='failed',
            status=None, value=None, attempts=2)], 'timeout_exhaustion_result_changed')

    def scoped_identity():
        one = job()
        seen = []
        def send(value, attempt):
            seen.append((value['tenant'], value['id']))
            return {'status': 200}
        rows = run([one, deepcopy(one), job(tenant='b')], send)
        require(seen == [('a', 'one'), ('b', 'one')] and len(rows) == 2, 'tenant_identity_or_coalescing_wrong')

    def conflict_before_effect():
        one = job()
        conflict = deepcopy(one)
        conflict['payload']['amount'] = 8
        seen = []
        raises(ValueError, lambda: run([job('earlier'), one, conflict], lambda *a: seen.append(a)))
        require(not seen, 'invalid_batch_partially_sent')

    def invalid_before_effect():
        invalid = job(method='POST')
        invalid.pop('idempotency_key')
        for jobs, limit in [([invalid], 3), ([job()], 0), ([job()], True)]:
            seen = []
            raises(ValueError, lambda: run(jobs, lambda *a: seen.append(a), max_attempts=limit))
            require(not seen, 'invalid_request_reached_sender')

    def unexpected_error():
        seen = []
        def send(value, attempt):
            seen.append(attempt)
            raise ValueError('bad sender configuration')
        raises(ValueError, lambda: run([job()], send))
        require(seen == [1], 'unexpected_error_retried')

    def mixed_batch():
        rows = run([job('bad'), job('good')], lambda value, attempt: {'status': 400 if value['id'] == 'bad' else 200})
        require([(r['id'], r['state']) for r in rows] == [('bad', 'failed'), ('good', 'ok')],
                'failed_job_hid_later_job_or_became_success')

    return collect('T1', [('retry-statuses', None, retries), ('terminal-500', 'retry-boundary', terminal_500),
        ('success-statuses', None, statuses), ('total-attempts', 'retry-boundary', total_limit),
        ('stable-immutable-request', 'request-integrity', timeout_and_immutability),
        ('timeout-exhaustion', None, timeout_exhaustion), ('scoped-identity', 'tenant-identity', scoped_identity),
        ('preflight-conflict', 'no-partial-invalid-batch', conflict_before_effect),
        ('invalid-input', 'no-partial-invalid-batch', invalid_before_effect),
        ('unexpected-error', None, unexpected_error), ('mixed-batch', None, mixed_batch)])


def database(version=1, rows=None):
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE schema_version(version INTEGER NOT NULL)')
    connection.execute('INSERT INTO schema_version VALUES (?)', (version,))
    workspace, archived = ('tenant', 'deleted') if version == 1 else ('workspace_id', 'archived')
    connection.execute(f'CREATE TABLE projects(id TEXT PRIMARY KEY,{workspace} TEXT NOT NULL,title TEXT NOT NULL,{archived} INTEGER NOT NULL DEFAULT 0)')
    connection.executemany('INSERT INTO projects VALUES (?,?,?,?)', rows or [('p1', 'a', '示例', 0)])
    connection.execute('CREATE TABLE notes(value TEXT)')
    connection.commit()
    return connection


def accept_t3(module):
    migrate = module.migrate
    def preservation():
        with closing(database(rows=[('p1', 'a', '同名🙂', 0), ('p2', 'b', '同名🙂', 1)])) as db:
            migrate(db)
            require(db.execute('SELECT * FROM schema_version').fetchall() == [(3,)], 'wrong_schema_version')
            require(db.execute('SELECT id,workspace_id,title,archived,row_version FROM projects ORDER BY id').fetchall()
                == [('p1', 'a', '同名🙂', 0, 1), ('p2', 'b', '同名🙂', 1, 1)], 'identity_or_history_destroyed')

    def uniqueness():
        with closing(database(rows=[('p2', 'a', 'same', 0), ('p1', 'a', 'same', 0),
                                    ('p3', 'b', 'same', 0), ('p4', 'a', 'same', 1)])) as db:
            migrate(db)
            require(db.execute('SELECT id,archived FROM projects ORDER BY id').fetchall()
                    == [('p1', 0), ('p2', 1), ('p3', 0), ('p4', 1)], 'duplicate_resolution_changed')
            raises(sqlite3.IntegrityError, lambda: db.execute("INSERT INTO projects VALUES ('p5','a','same',0,1)"))
            db.execute("INSERT INTO projects VALUES ('p6','a','same',1,1)")
            db.execute("INSERT INTO projects VALUES ('p7','c','same',0,1)")

    def replay():
        with closing(database()) as db:
            migrate(db)
            db.execute("UPDATE projects SET row_version=7,title='changed' WHERE id='p1'")
            before = list(db.iterdump())
            migrate(db)
            require(list(db.iterdump()) == before, 'replay_reset_committed_state')

    def version_two():
        with closing(database(version=2)) as db:
            migrate(db)
            require(db.execute('SELECT workspace_id,row_version FROM projects').fetchall() == [('a', 1)], 'v2_upgrade_failed')

    def unsupported():
        with closing(database()) as db:
            db.execute('UPDATE schema_version SET version=9')
            before = list(db.iterdump())
            raises(ValueError, lambda: migrate(db))
            require(list(db.iterdump()) == before, 'unsupported_version_changed')

    def multiple_versions():
        with closing(database()) as db:
            db.execute('INSERT INTO schema_version VALUES (2)')
            before = list(db.iterdump())
            raises(ValueError, lambda: migrate(db))
            require(list(db.iterdump()) == before, 'ambiguous_version_changed')

    def atomic_failure():
        with closing(database()) as db:
            db.execute("INSERT INTO notes VALUES ('caller-pending')")
            before = list(db.iterdump())
            db.set_authorizer(lambda action, first, *args: sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_UPDATE and first == 'schema_version' else sqlite3.SQLITE_OK)
            try:
                raises(sqlite3.DatabaseError, lambda: migrate(db))
            finally:
                db.set_authorizer(None)
            require(list(db.iterdump()) == before and db.in_transaction, 'failed_migration_not_atomic')

    def caller_transaction():
        with closing(database()) as db:
            db.execute("INSERT INTO notes VALUES ('pending')")
            migrate(db)
            require(db.in_transaction, 'migration_committed_caller_transaction')
            db.rollback()
            require(db.execute('SELECT version FROM schema_version').fetchone() == (1,), 'outer_rollback_failed')
            require(db.execute('SELECT * FROM notes').fetchall() == [], 'caller_pending_write_committed')

    def conflicting_table():
        with closing(database()) as db:
            db.execute('CREATE TABLE projects_migrating(sentinel TEXT)')
            db.execute("INSERT INTO projects_migrating VALUES ('keep')")
            before = list(db.iterdump())
            raises(sqlite3.DatabaseError, lambda: migrate(db))
            require(list(db.iterdump()) == before, 'unrelated_staging_table_deleted')

    def incomplete_version_three():
        with closing(database(version=2)) as db:
            db.execute('UPDATE schema_version SET version=3')
            before = list(db.iterdump())
            raises(ValueError, lambda: migrate(db))
            require(list(db.iterdump()) == before, 'malformed_v3_silently_accepted_or_changed')

    return collect('T3', [('preserve-rows', 'history-preservation', preservation),
        ('scoped-unique', 'workspace-identity', uniqueness), ('replay', 'no-state-reset', replay),
        ('upgrade-v2', None, version_two), ('unsupported-version', 'version-boundary', unsupported),
        ('ambiguous-version', 'version-boundary', multiple_versions),
        ('failure-atomic', 'transaction-atomicity', atomic_failure),
        ('caller-transaction', 'transaction-ownership', caller_transaction),
        ('staging-name-conflict', 'unrelated-data-preservation', conflicting_table),
        ('incomplete-v3', 'version-boundary', incomplete_version_three)])
