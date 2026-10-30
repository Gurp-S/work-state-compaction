"""Existing schema migration entry; caller owns the connection transaction."""


def migrate(connection):
    connection.execute('ALTER TABLE projects RENAME COLUMN tenant TO workspace_id')
    connection.execute('ALTER TABLE projects RENAME COLUMN deleted TO archived')
    connection.execute('DELETE FROM projects WHERE archived=1')
    connection.execute('CREATE UNIQUE INDEX active_title ON projects(title)')
    connection.execute('UPDATE schema_version SET version=3')
    connection.commit()
