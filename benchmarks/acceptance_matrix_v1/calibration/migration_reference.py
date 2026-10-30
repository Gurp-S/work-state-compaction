"""Calibration reference only; source and expected policy remain coordinator-side."""


def migrate(connection):
    versions = connection.execute('SELECT version FROM schema_version').fetchall()
    if len(versions) != 1 or type(versions[0][0]) is not int or versions[0][0] not in (1, 2, 3):
        raise ValueError('schema_version_unsupported')
    version = versions[0][0]
    if version == 3:
        columns = {r[1] for r in connection.execute('PRAGMA table_info(projects)')}
        if columns != {'id', 'workspace_id', 'title', 'archived', 'row_version'}:
            raise ValueError('schema_shape_invalid')
        return
    workspace, archived = ('tenant', 'deleted') if version == 1 else ('workspace_id', 'archived')
    rows = connection.execute(f'SELECT id,{workspace},title,{archived} FROM projects ORDER BY id').fetchall()
    if any(r[3] not in (0, 1) for r in rows):
        raise ValueError('archive_flag_invalid')
    connection.execute('SAVEPOINT wsc_fixture_migration')
    try:
        connection.execute('CREATE TABLE projects_migrating(id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, row_version INTEGER NOT NULL DEFAULT 1)')
        active = set()
        for identity, tenant, title, deleted in rows:
            key = (tenant, title)
            flag = int(deleted or key in active)
            if not flag:
                active.add(key)
            connection.execute('INSERT INTO projects_migrating VALUES (?,?,?,?,1)', (identity, tenant, title, flag))
        connection.execute('DROP TABLE projects')
        connection.execute('ALTER TABLE projects_migrating RENAME TO projects')
        connection.execute('CREATE UNIQUE INDEX active_title ON projects(workspace_id,title) WHERE archived=0')
        connection.execute('UPDATE schema_version SET version=3')
        connection.execute('RELEASE SAVEPOINT wsc_fixture_migration')
    except BaseException:
        connection.execute('ROLLBACK TO SAVEPOINT wsc_fixture_migration')
        connection.execute('RELEASE SAVEPOINT wsc_fixture_migration')
        raise
