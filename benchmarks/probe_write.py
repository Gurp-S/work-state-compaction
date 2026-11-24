"""写入路径探针：把 turn 5 的三条抽取结果直接喂进写库链路，逐步打印每步结果。

    py -3.11 benchmarks/probe_write.py
输出：benchmarks/results/probe_write.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm.cem import slot_naming  # noqa: E402
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate  # noqa: E402

PERSONA = "PUB01"
TURN = 5
EVENT_ID = f"{PERSONA}/turn/{TURN:04d}"
HISTORY = ROOT / ".bench/memory-system-benchmark/demo/histories/PUB01.jsonl"

ROWS = [
    {"entity": "用户", "slot": "借入物品", "value": "上周阿岑借给用户一把活动扳手", "topics": ["活动扳手", "借"]},
    {"entity": "用户", "slot": "归还约定", "value": "约定演出结束后把活动扳手还给阿岑", "topics": ["归还", "演出"]},
    {"entity": "助手", "slot": "建议", "value": "等演出收工后再归还活动扳手", "topics": ["归还", "演出"]},
]


def main() -> int:
    out_path = ROOT / "benchmarks" / "results" / "probe_write.db"
    if out_path.exists():
        out_path.unlink()
    rows = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()]
    turn = rows[TURN - 1]

    service = CSM(CsmStore(str(out_path), namespace="probe"))
    service.ingest([Event(id=EVENT_ID, source_type="chat",
                          payload={"user": turn["用户消息"], "assistant": turn["助手回复"]},
                          observed_at=turn["逻辑时间"])])

    slots: dict[str, set[str]] = {}
    normalized = []
    for item in ROWS:
        before = item["slot"]
        item["slot"] = slot_naming.normalize(item["slot"], slots.setdefault(item["entity"], set()))
        normalized.append({"entity": item["entity"], "slot_before": before, "slot_after": item["slot"]})
        slots[item["entity"]].add(item["slot"])

    result = service.remember(
        [MemoryCandidate(entity=i["entity"], slot=i["slot"], value=i["value"], contexts=(),
                         topics=tuple(i["topics"]), source_ids=(EVENT_ID,)) for i in ROWS],
        producer="probe")

    con = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0]
              for t in ("events", "identities", "heads", "projection", "revisions")}
    hits = []
    for table in ("projection", "identities"):
        try:
            rows_out = con.execute(f"select * from {table} where data like ?", ("%扳手%",)).fetchall()
        except sqlite3.Error:
            rows_out = []
        hits.append({"table": table, "rows": [list(map(str, r)) for r in rows_out]})

    payload = {"event_id": EVENT_ID, "user": turn["用户消息"], "normalized": normalized,
               "remember_result": str(result), "counts": counts, "hits": hits}
    (ROOT / "benchmarks" / "results" / "probe_write.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("counts", counts, "hits", [(h["table"], len(h["rows"])) for h in hits])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
