import json
import sqlite3

db = sqlite3.connect(r"D:\lea\XenYon code\wsc\benchmarks\results\public-exam-full.db")
db.row_factory = sqlite3.Row
rows = db.execute("select data from identities").fetchall()
print("identities", len(rows))
hits = [r["data"] for r in rows if "温室" in r["data"] or "greenhouse" in r["data"].lower()]
for h in hits[:5]:
    print(h[:220])
print("---- C004")
for r in db.execute("select data from identities"):
    d = json.loads(r["data"])
    if "C004" in d["memory_id"]:
        print(d["entity"], "|", d["slot"], "|", d["value"][:100])
