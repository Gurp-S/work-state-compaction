import json
from pathlib import Path

from wsc.csm import CSM, CsmStore, Event, MemoryCandidate
from wsc.csm import shadow, tree

db_path = Path(".bench/shadow-test.db")
db_path.unlink(missing_ok=True)
store = CsmStore(db_path, namespace="shadow")
service = CSM(store)
service.ingest([Event(id="e1", source_type="chat", payload={"text": "t"})])
service.remember([MemoryCandidate(entity="Alice", slot="job", value="product manager at Acme",
                                  source_ids=("e1",))], producer="t")

with store.transaction() as db:
    node = tree.create_node(db, name="Acme", node_type="organization", status="active",
                            scope_description="Acme workplace facts",
                            recorded_at="2026-01-01T00:00:00+00:00")
    tree.mount(db, "alice:job", node["node_id"], recorded_at="2026-01-01T00:00:02+00:00")

with store.connect() as db:
    report = shadow.evaluate(db, [{"op": "retire", "node_id": node["node_id"]}])
    print(json.dumps({k: report[k] for k in ("ok", "violations", "improvement")}, ensure_ascii=False))
    report2 = shadow.evaluate(db, [{"op": "create_node", "name": "Acme EU", "parent_id": node["node_id"]}])
    print(json.dumps({k: report2[k] for k in ("ok", "violations", "improvement")}, ensure_ascii=False))
    ok = shadow.apply(db, [{"op": "create_node", "name": "Acme EU", "parent_id": node["node_id"]}],
                      recorded_at="2026-01-02T00:00:00+00:00")
    print("applied", ok["report"]["ok"], len(ok["results"]))
