"""Opt-in implementation-neutral T3 audit; original acceptor/results unchanged."""
from contextlib import closing
import sqlite3
from .acceptors import accept_t3, database, collect, require


class UnassessableStaging(Exception):
    pass


def rejects(call):
    try:
        call()
    except Exception:
        return
    raise AssertionError('expected_rejection')


def quoted(name):
    return '"'+name.replace('"','""')+'"'


def snapshot(db):
    temp=[]
    for name,sql in db.execute('SELECT name,sql FROM sqlite_temp_master WHERE type="table" ORDER BY name'):
        temp.append((name,sql,db.execute('SELECT * FROM temp.'+quoted(name)).fetchall()))
    return list(db.iterdump()),temp,db.in_transaction


def migrated_fixture(db):
    require(db.execute("SELECT type FROM main.sqlite_master WHERE name='projects'").fetchone()==('table',),'persistent_projects_missing')
    require({r[1] for r in db.execute('PRAGMA main.table_info(projects)')}=={'id','workspace_id','title','archived','row_version'},'persistent_layout_changed')
    require(db.execute('SELECT version FROM main.schema_version').fetchall()==[(3,)],'probe_migration_failed')
    require(db.execute('SELECT id,workspace_id,title,archived,row_version FROM main.projects').fetchall()==[('p1','a','示例',0,1)],'probe_rows_changed')


def preservation_check(migrate):
    """Discover names through SQLite events; never inspect candidate source/AST."""
    stages=set()
    for version in (1,2):
        with closing(database(version=version)) as db:
            existing={('main',r[0]) for r in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            unsupported=[]
            def observe(action,name,second,schema,trigger):
                if action in (sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_CREATE_TEMP_TABLE) and (schema,name) not in existing and not name.startswith('sqlite_'):
                    if schema not in ('main','temp'):unsupported.append(schema)
                    else:stages.add((schema,name))
                return sqlite3.SQLITE_OK
            db.set_authorizer(observe)
            migrate(db)
            if unsupported:raise UnassessableStaging('attached_schema_preservation_not_covered')
            migrated_fixture(db)
    # This table is arbitrary unrelated state, rather than a reserved implementation name.
    targets=stages | {('main','unrelated_customer_table')}
    for schema,name in sorted(targets):
        for layout in ('sentinel','target'):
            with closing(database()) as db:
                qualified=schema+'.'+quoted(name)
                if layout=='sentinel':
                    db.execute('CREATE TABLE '+qualified+'(sentinel TEXT)')
                    db.execute('INSERT INTO '+qualified+" VALUES ('keep')")
                else:
                    db.execute('CREATE TABLE '+qualified+'(id TEXT,workspace_id TEXT,title TEXT,archived INTEGER,row_version INTEGER)')
                    db.execute('INSERT INTO '+qualified+" VALUES ('sentinel','other','keep',0,47)")
                before=snapshot(db)
                original=db.execute('SELECT * FROM '+qualified).fetchall()
                original_sql=db.execute('SELECT sql FROM '+schema+'.sqlite_master WHERE name=?',(name,)).fetchone()
                try:
                    migrate(db)
                except Exception:
                    require(snapshot(db)==before,'rejection_mutated_existing_state')
                else:
                    require(db.execute('SELECT * FROM '+qualified).fetchall()==original,'preexisting_rows_changed')
                    require(db.execute('SELECT sql FROM '+schema+'.sqlite_master WHERE name=?',(name,)).fetchone()==original_sql,'preexisting_schema_changed')
                    migrated_fixture(db)
                    require(db.in_transaction,'successful_call_committed_caller')
    return dict(observed_stage_names=[dict(schema=s,name=n) for s,n in sorted(stages)],
                layouts=['sentinel','target'],tested_preservation_cases=len(targets)*2,
                discovery='SQLite CREATE events on authored v1/v2 fixtures, no candidate source analysis')


def accept_t3_v2(module):
    legacy=accept_t3(module)
    migrate=module.migrate
    coverage={}
    def unsupported():
        with closing(database()) as db:
            db.execute('UPDATE schema_version SET version=9');before=snapshot(db)
            rejects(lambda:migrate(db));require(snapshot(db)==before,'unsupported_version_changed')
    def multiple():
        with closing(database()) as db:
            db.execute('INSERT INTO schema_version VALUES (2)');before=snapshot(db)
            rejects(lambda:migrate(db));require(snapshot(db)==before,'ambiguous_version_changed')
    def atomic():
        with closing(database()) as db:
            db.execute("INSERT INTO notes VALUES ('caller-pending')");before=snapshot(db)
            db.set_authorizer(lambda action,first,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and first=='schema_version' else sqlite3.SQLITE_OK)
            try:rejects(lambda:migrate(db))
            finally:db.set_authorizer(None)
            require(snapshot(db)==before,'failed_migration_not_atomic')
    def malformed():
        with closing(database(version=2)) as db:
            db.execute('UPDATE schema_version SET version=3');before=snapshot(db)
            rejects(lambda:migrate(db));require(snapshot(db)==before,'malformed_v3_changed')
    def staged():coverage.update(preservation_check(migrate))
    replacements=collect('T3',[
        ('unsupported-version','version-boundary',unsupported),('ambiguous-version','version-boundary',multiple),
        ('failure-atomic','transaction-atomicity',atomic),('incomplete-v3','version-boundary',malformed),
        ('staging-and-unrelated-preservation','unrelated-data-preservation',staged)])
    changed={r['check_id'] for r in replacements['checks']} | {'staging-name-conflict'}
    rows=[r for r in legacy['checks'] if r['check_id'] not in changed]+replacements['checks']
    for row in rows:
        if row.get('error_type')=='UnassessableStaging':row.update(passed=None,status='unassessable')
    assessed=sum(r['passed'] is not None for r in rows)
    success=False if any(r['passed'] is False for r in rows) else None if assessed<len(rows) else True
    return dict(task='T3',evaluator_policy='implementation_neutral_t3_v2',success=success,checks=rows,
        assessed_checks=assessed,unassessable_checks=len(rows)-assessed,
        constraint_violations=sorted({r['constraint_id'] for r in rows if r['passed'] is False and r['constraint_id']}),
        staging_coverage=coverage,legacy_result=legacy,
        scope='Post-hoc deterministic audit unless separately preregistered; legacy scores retained.')
