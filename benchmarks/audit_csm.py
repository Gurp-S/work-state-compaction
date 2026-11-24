"""契约审计：每个声明过的字段/能力，必须能被观测到真的生效。

不花 LLM：全部在真实库上做行为探针，输出 PASS / NO-OP / UNVERIFIABLE。
NO-OP 就是"声明了但静默无效"，这类比报错危险，因为调用方会以为自己拿到了结果。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import csm_public_exam as E  # noqa: E402

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmarks/results/ab3.db")
NS = sys.argv[2] if len(sys.argv) > 2 else "public-exam:PUB01"
rows: list[tuple[str, str, str]] = []


def record(name: str, verdict: str, detail: str = "") -> None:
    rows.append((name, verdict, detail))


def probe(name, fn):
    try:
        verdict, detail = fn()
    except Exception as exc:  # noqa: BLE001 - an audit reports, it does not raise
        verdict, detail = "ERROR", f"{type(exc).__name__}: {exc}"[:80]
    record(name, verdict, detail)


svc = E.CSM(E.CsmStore(DB, namespace=NS))
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row


def _first_sql(sql, *params):
    row = con.execute(sql, params).fetchone()
    return row[0] if row else None


def _count(sql, *params):
    return int(con.execute(sql, params).fetchone()[0])


def q(**kwargs):
    return svc.query(E.MemoryQuery(**kwargs))["results"]


def check_entity():
    items = q(entity="用户", limit=50)
    if not items:
        return "UNVERIFIABLE", "no rows for 用户"
    bad = [i for i in items if i.get("entity") != "用户"]
    return ("PASS", f"{len(items)} rows") if not bad else ("NO-OP", f"{len(bad)} foreign rows")


def check_slot():
    slot = _first_sql("SELECT slot FROM identities WHERE slot != '' LIMIT 1")
    if not slot:
        return "UNVERIFIABLE", "no slots"
    items = q(slot=slot, limit=50)
    bad = [i for i in items if i.get("slot") != slot]
    return ("PASS", f"{len(items)} rows") if items and not bad else ("NO-OP", f"{len(bad)} foreign rows")


def check_contexts():
    ctx = _first_sql("SELECT contexts FROM identities WHERE contexts NOT IN ('','[]') LIMIT 1")
    if not ctx:
        return "UNVERIFIABLE", "no contexts stored"
    values = json.loads(ctx)
    if not values:
        return "UNVERIFIABLE", "empty contexts"
    items = q(contexts=(values[0],), limit=50)
    bad = [i for i in items if values[0] not in (i.get("contexts") or [])]
    return ("PASS", f"{len(items)} rows") if items and not bad else ("NO-OP", f"{len(bad)} foreign rows")


def check_topics():
    topic = _first_sql("SELECT topic FROM memory_topics LIMIT 1")
    if not topic:
        return "UNVERIFIABLE", "no topics stored"
    items = q(topics=(topic,), limit=50)
    bad = [i for i in items if topic not in (i.get("topics") or [])]
    return ("PASS", f"{len(items)} rows") if items and not bad else ("NO-OP", f"{len(bad)} foreign rows")


def check_node_id():
    nodes = _count("SELECT COUNT(*) FROM tree_nodes")
    mounts = _count("SELECT COUNT(*) FROM tree_mounts")
    if not nodes:
        return "UNVERIFIABLE", "no tree nodes"
    if not mounts:
        return "NO-OP", f"{nodes} nodes, 0 mounts: nothing is ever scoped to a node"
    node = _first_sql("SELECT node_id FROM tree_mounts LIMIT 1")
    items = q(node_id=node, limit=50)
    return ("PASS", f"{len(items)} rows") if items else ("NO-OP", "node scope returned nothing")


def check_valid_at():
    instant = "2026-06-01T00:00:00+08:00"
    items = q(entity="用户", valid_at=instant, limit=500)
    if not items:
        return "UNVERIFIABLE", "nothing existed then"
    late = [i for i in items if str(i.get("effective_at") or "") > instant]
    return ("PASS", f"{len(items)} rows") if not late else ("NO-OP", f"{len(late)} future rows")


def check_expand():
    if not _count("SELECT COUNT(*) FROM relations"):
        return "UNVERIFIABLE", "no relations: expand has nothing to walk"
    base = q(entity="用户", limit=10)
    grown = q(entity="用户", limit=10, expand=2)
    if not base:
        return "UNVERIFIABLE", "no rows"
    return ("PASS", f"{len(base)} -> {len(grown)}") if len(grown) != len(base) else (
        "NO-OP", "expand changed nothing")


def check_relation_kinds():
    if not _count("SELECT COUNT(*) FROM relations"):
        return "UNVERIFIABLE", "no relations stored"
    plain = q(entity="用户", limit=50)
    filtered = q(entity="用户", limit=50, relation_kinds=("CONSTRAINT",))
    return ("PASS", f"{len(plain)} -> {len(filtered)}") if len(filtered) != len(plain) else (
        "NO-OP", "relation_kinds changed nothing")


def check_dependencies():
    items = q(entity="用户", limit=5, include_dependencies=True)
    return ("PASS", "dependencies attached") if any("dependencies" in i for i in items) else (
        "NO-OP", "no dependencies key")


def check_history():
    mid = _first_sql("SELECT memory_id FROM revisions GROUP BY memory_id "
                     "HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT 1")
    if not mid:
        return "UNVERIFIABLE", "no superseded memories"
    ident = json.loads(_first_sql("SELECT data FROM identities WHERE memory_id = ?", mid))
    items = q(entity=ident["entity"], slot=ident["slot"], include_history=True, limit=50)
    old = sum(1 for i in items if i.get("classification") == "HISTORICAL")
    return ("PASS", f"{old} historical of {len(items)}") if old else ("NO-OP", "no historical rows")


def check_pending():
    if not _count("SELECT COUNT(*) FROM pending"):
        return "UNVERIFIABLE", "no pending bindings"
    on = q(entity="用户", limit=200, include_pending=True)
    off = q(entity="用户", limit=200, include_pending=False)
    return ("PASS", f"{len(on)} vs {len(off)}") if len(on) != len(off) else (
        "NO-OP", "include_pending changed nothing")


def check_limit():
    items = q(entity="用户", limit=7)
    return ("PASS", f"{len(items)} rows") if len(items) <= 7 else ("NO-OP", f"{len(items)} > 7")


def check_text_ranking():
    items = q(entity="用户", limit=8, text="住几楼")
    if not items:
        return "UNVERIFIABLE", "no rows"
    hits = [int(i.get("lexical_hits") or 0) for i in items]
    return ("PASS", f"hits {hits[:4]}") if max(hits) > 0 else ("NO-OP", "every row scored 0")


def check_search_window():
    late = svc.search("住几楼", limit=12)["results"]
    early = svc.search("住几楼", limit=12, window=(None, "2026-02-01T00:00:00+08:00"))["results"]
    if not late:
        return "UNVERIFIABLE", "no hits"
    future = [i for i in early if str(i.get("effective_at") or "") > "2026-02-01T00:00:00+08:00"]
    return ("PASS", f"{len(late)} -> {len(early)}") if not future else (
        "NO-OP", f"{len(future)} future hits")


def check_pending_type():
    from wsc.csm import contracts
    kinds = set(contracts.PENDING_TYPES)
    stored = {r[0] for r in con.execute("SELECT DISTINCT kind FROM pending")} if _count(
        "SELECT COUNT(*) FROM pending") else set()
    if not stored:
        return "UNVERIFIABLE", "no pending rows"
    return ("PASS", f"{sorted(stored)}") if stored <= kinds else ("NO-OP", f"unknown kinds {stored - kinds}")


for name, fn in [
    ("entity", check_entity), ("slot", check_slot), ("contexts", check_contexts),
    ("topics", check_topics), ("node_id", check_node_id), ("valid_at", check_valid_at),
    ("expand", check_expand), ("relation_kinds", check_relation_kinds),
    ("include_dependencies", check_dependencies), ("include_history", check_history),
    ("include_pending", check_pending), ("limit", check_limit), ("text", check_text_ranking),
    ("search.window", check_search_window), ("pending.kinds", check_pending_type),
]:
    probe(name, fn)

width = max(len(n) for n, _, _ in rows)
for name, verdict, detail in rows:
    print(f"{name.ljust(width)}  {verdict:<12}  {detail}")
print("\nNO-OP:", sum(1 for _, v, _ in rows if v == "NO-OP"),
      "ERROR:", sum(1 for _, v, _ in rows if v == "ERROR"),
      "UNVERIFIABLE:", sum(1 for _, v, _ in rows if v == "UNVERIFIABLE"))
