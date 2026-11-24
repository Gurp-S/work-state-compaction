import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm import CSM, CsmStore  # noqa: E402
from wsc.csm import retrieval  # noqa: E402

BENCH = ROOT / ".bench" / "Locomo-Plus"
DB = ROOT / "benchmarks" / "results" / "locomo-qa-conv0.db"
data = json.loads((BENCH / "data" / "locomo10.json").read_text(encoding="utf-8"))
service = CSM(CsmStore(DB, namespace="locomo0"))
shown = 0
with service.store.connect() as db:
    for q in data[0]["qa"]:
        if str(q.get("category")) != "4" or shown >= 6:
            continue
        items = retrieval.search(db, q["question"], limit=5)["results"]
        print("Q:", q["question"])
        print("GOLD:", q.get("answer"))
        for item in items:
            print("  -", item["memory_id"], "|", str(item.get("value"))[:160])
        print()
        shown += 1
