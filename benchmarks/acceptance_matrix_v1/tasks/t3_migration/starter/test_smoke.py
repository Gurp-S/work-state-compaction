from contextlib import closing
import sqlite3
import unittest
from migrate import migrate


class MigrationSmoke(unittest.TestCase):
    def test_row_version_exists_and_replay_succeeds(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute('CREATE TABLE schema_version(version INTEGER NOT NULL)')
            connection.execute('INSERT INTO schema_version VALUES (1)')
            connection.execute('CREATE TABLE projects(id TEXT PRIMARY KEY, tenant TEXT NOT NULL, title TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)')
            connection.execute("INSERT INTO projects VALUES ('p1','a','Example',0)")
            migrate(connection)
            migrate(connection)
            self.assertIn('row_version', [r[1] for r in connection.execute('PRAGMA table_info(projects)')])


if __name__ == '__main__':
    unittest.main()
