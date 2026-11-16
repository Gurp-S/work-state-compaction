"""Store one complete current-state projection, including retrieval metadata."""
import json


def put(db, payload):
    db.execute("INSERT INTO projection(memory_id, data) VALUES(?, ?) "
               "ON CONFLICT(memory_id) DO UPDATE SET data = excluded.data "
               "WHERE projection.data <> excluded.data",
               (payload["memory_id"], json.dumps(payload, sort_keys=True, ensure_ascii=False)))
