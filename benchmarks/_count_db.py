import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print("tables:", sorted(tables))
for name in ("identities", "memory_revisions", "pending_candidates", "memory_topics"):
    if name in tables:
        print(name, db.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
