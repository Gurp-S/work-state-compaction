import json
import sqlite3

c = sqlite3.connect("benchmarks/results/public-exam-full.db")
c.row_factory = sqlite3.Row
print([row[1] for row in c.execute("pragma table_info(projection)")])
for row in c.execute("select * from projection"):
    data = json.loads(row["data"])
    print(data.get("created_at"), row["memory_id"], "|", data.get("value"))
