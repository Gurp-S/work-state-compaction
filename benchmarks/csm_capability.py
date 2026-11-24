"""Zero-token capability matrix for CSM: 54 deterministic assertions over the core.

    python benchmarks/csm_capability.py [--out PATH]

Each case runs against a fresh store; nothing calls a model. The output is the matrix the
recall report is read against: a low recall with a green matrix points at data/scoping, a red
matrix means the engine contract itself is broken.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wsc.csm import (CSM, CSMError, CsmStore, Event, MemoryCandidate, MemoryQuery,
                     branch_scope, repo_scope)  # noqa: E402

ENTITY = "acme/api"
REPO = repo_scope(ENTITY)
MAIN = branch_scope(ENTITY, "main")
A, B, C = "a" * 40, "b" * 40, "c" * 40
T1, T2, T3 = "2026-02-01T00:00:00Z", "2026-04-01T00:00:00Z", "2026-06-01T00:00:00Z"


class Matrix:
    def __init__(self, root: Path):
        self.root = root
        self.db = root / "memory.db"
        self.core = CSM(CsmStore(self.db, namespace="case"))
        self.core.ingest([
            Event("c1", "git", {"text": "observed c1"}, observed_at=T1,
                  source_ref=A, metadata={"commit": A, "kind": "git"}),
            Event("c2", "git", {"text": "observed c2"}, observed_at=T2,
                  source_ref=B, metadata={"commit": B, "kind": "git"}),
            Event("c3", "git", {"text": "observed c3"}, observed_at=T3,
                  source_ref=C, metadata={"commit": C, "kind": "git"}),
        ])

    def mem(self, **overrides):
        data = {"entity": ENTITY, "slot": "runtime", "value": "python3.10",
                "scope": REPO, "source_ids": ("c1",)}
        data.update(overrides)
        return self.core.remember([MemoryCandidate(**data)])[0]

    def query(self, **overrides):
        data = {"entity": ENTITY, "slot": "runtime", "with_evidence": False}
        data.update(overrides)
        return self.core.query(MemoryQuery(**data))

    def value(self, **overrides):
        packet = self.query(**overrides)
        return packet["results"][0].get("value") if packet["results"] else None


# ---------------------------------------------------------------- identity
def a1_first_write(m):
    row = m.mem()
    assert row["operation"] == "create" and row["revision"] == 1, row


def a2_duplicate(m):
    first = m.mem()
    again = m.mem()
    assert not again["changed"] and again["revision"] == first["revision"], again


def a3_overwrite(m):
    m.mem()
    second = m.mem(value="python3.12", source_ids=("c2",))
    assert second["operation"] == "update" and second["revision"] == 2, second
    assert m.value() == "python3.12"


def a4_event_append(m):
    one = m.mem(slot="decision", value="use postgres")
    two = m.mem(slot="decision", value="use sqlite", source_ids=("c2",))
    assert one["memory_id"] != two["memory_id"], (one, two)
    assert m.query(slot="decision")["counts"]["CURRENT_CONFIRMED"] == 2


def a5_alias(m):
    first = m.mem()
    m.core.alias_property(first["property_id"], "运行时")
    again = m.mem(slot="运行时", value="python3.12", source_ids=("c2",))
    assert again["memory_id"] == first["memory_id"] and again["revision"] == 2, again


def a6_event_inference(m):
    assert m.mem(slot="decision")["property_kind"] == "event"


def a7_state_inference(m):
    assert m.mem(slot="build_command")["property_kind"] == "state"


def a8_explicit_kind(m):
    assert m.mem(slot="note", property_kind="state")["property_kind"] == "state"


# ---------------------------------------------------------------- scope
def b1_default_scope(m):
    row = m.mem(scope=None)
    assert row["origin_scope"] == "entity", row


def b2_repo_isolation(m):
    m.mem()
    other = m.mem(entity="other/api", scope=repo_scope("other/api"),
                  value="node20", source_ids=("c2",))
    listed = m.query(scope=REPO)["results"]
    assert len(listed) == 1 and listed[0]["memory_id"] != other["memory_id"], listed


def b3_branch_overrides(m):
    m.mem()
    m.mem(value="python3.12", scope=MAIN, source_ids=("c2",))
    results = m.query(scope=MAIN, scope_chain=True)["results"]
    assert len(results) == 1 and results[0]["value"] == "python3.12", results


def b4_exact_hides_repo(m):
    m.mem()
    assert m.query(scope=MAIN)["results"] == []


def b5_earlier_commit_falls_back(m):
    m.mem()
    m.mem(value="python3.12", scope=MAIN, source_ids=("c2",))
    old = m.query(scope=MAIN, scope_chain=True, valid_at=T1)["results"]
    assert len(old) == 1 and old[0]["value"] == "python3.10", old


def b6_event_visible_by_scope(m):
    row = m.mem(slot="decision", value="use postgres")
    packet = m.core.memory(row["memory_id"])
    assert packet["origin_scope"] == REPO, packet
    assert packet["scope"].startswith("event:"), packet


def b7_cross_repo(m):
    m.mem()
    assert m.query(entity="other/api", slot="runtime")["results"] == []


# ---------------------------------------------------------------- time
def c1_before_history(m):
    m.mem()
    packet = m.query(valid_at="2026-01-01T00:00:00Z")
    assert packet["counts"]["UNKNOWN"] == 1 and packet["results"][0]["confirmed"] is False


def c2_between(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    assert m.query(valid_at="2026-03-01T00:00:00Z")["results"][0]["value"] == "python3.10"


def c3_after(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    assert m.query(valid_at="2026-05-01T00:00:00Z")["results"][0]["value"] == "python3.12"


def c4_commit_historical(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    row = m.query(at_commit=A)["results"][0]
    assert row["value"] == "python3.10" and row["classification"] == "HISTORICAL", row


def c5_commit_current(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    row = m.query(at_commit=B)["results"][0]
    assert row["value"] == "python3.12" and row["classification"] == "CURRENT_CONFIRMED"


def c6_unknown_commit(m):
    try:
        m.query(at_commit="f" * 40)
    except CSMError as error:
        assert "commit_unknown" in str(error), error
        return
    raise AssertionError("unknown commit accepted")


def c7_ambiguous_time(m):
    try:
        m.query(at_commit=A, valid_at=T1)
    except CSMError as error:
        assert "query_time_ambiguous" in str(error), error
        return
    raise AssertionError("ambiguous time accepted")


def c8_history(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    packet = m.query(include_history=True)
    assert packet["counts"]["HISTORICAL"] == 1, packet["counts"]


# ---------------------------------------------------------------- evidence
def d1_evidence_text(m):
    m.mem()
    row = m.query(with_evidence=True)["results"][0]
    assert row["evidence"][0]["text"] == "observed c1", row["evidence"]


def d2_evidence_truncated(m):
    m.core.ingest([Event("long", "file", {"text": "x" * 1000}, observed_at=T3)])
    m.mem(source_ids=("long",))
    row = m.query(with_evidence=True)["results"][0]
    assert len(row["evidence"][0]["text"]) == 700, len(row["evidence"][0]["text"])


def d3_missing_source(m):
    try:
        m.mem(source_ids=("missing",))
    except CSMError as error:
        assert "evidence_source_unknown" in str(error), error
        return
    raise AssertionError("unknown evidence accepted")


def d4_commit_on_revision(m):
    m.mem()
    assert m.query()["results"][0]["commit"] == A


def d5_event_partition(m):
    row = m.mem(slot="decision")
    packet = m.core.memory(row["memory_id"])
    assert packet["scope"] != REPO and packet["origin_scope"] == REPO, packet


def d6_metadata_persisted(m):
    with closing(sqlite3.connect(m.db)) as db:
        data, metadata, source_ref = db.execute(
            "SELECT data, metadata, source_ref FROM events WHERE id = 'c1'").fetchone()
    assert A in json.loads(metadata)["commit"] and source_ref == A, (metadata, source_ref)


# ---------------------------------------------------------------- redaction
def e1_payload(m):
    result = m.core.ingest([Event("secret", "file", {"text": "password=hunter2secret"},
                                  observed_at=T1)])
    assert result["redacted"] >= 1, result
    with closing(sqlite3.connect(m.db)) as db:
        data = db.execute("SELECT data FROM events WHERE id = 'secret'").fetchone()[0]
    assert "hunter2secret" not in data and "[REDACTED" in data, data


def e2_value(m):
    m.mem(value="password=hunter2secret")
    stored = m.value()
    assert "hunter2secret" not in str(stored) and "[REDACTED" in str(stored), stored


def e3_metadata(m):
    m.core.ingest([Event("meta", "file", {"text": "x"}, observed_at=T1,
                         metadata={"token": "keep-out"})])
    with closing(sqlite3.connect(m.db)) as db:
        metadata = db.execute("SELECT metadata FROM events WHERE id = 'meta'").fetchone()[0]
    assert "keep-out" not in metadata, metadata


def e4_search(m):
    m.mem(slot="deploy", value="password=hunter2secret")
    text = json.dumps(m.core.search("password"), ensure_ascii=False)
    assert "hunter2secret" not in text and "[REDACTED" in text, text


def e5_digest_stable(m):
    event = Event("secret", "file", {"text": "password=hunter2secret"}, observed_at=T1)
    first = m.core.ingest([event])
    second = m.core.ingest([event])
    assert first["redacted"] >= 1 and second["ingested"] == [] and second["existing"] == ["secret"]


# ---------------------------------------------------------------- consistency
def f1_event_idempotent(m):
    result = m.core.ingest([Event("c1", "git", {"text": "observed c1"}, observed_at=T1,
                                  metadata={"commit": A})])
    assert result["existing"] == ["c1"], result


def f2_event_conflict(m):
    try:
        m.core.ingest([Event("c1", "git", {"text": "different"}, observed_at=T1)])
    except CSMError as error:
        assert "event_conflict" in str(error), error
        return
    raise AssertionError("conflicting event accepted")


def f3_duplicate_memory(m):
    m.mem()
    m.mem()
    assert m.core.status()["revisions"] == 1


def f4_cas(m):
    m.mem()
    try:
        m.mem(value="x", expected_revision=9, source_ids=("c2",))
    except CSMError as error:
        assert "memory_revision_conflict" in str(error), error
        return
    raise AssertionError("stale revision accepted")


def f5_concurrent_entities(m):
    def write(index):
        m.core.remember([MemoryCandidate(entity=f"e{index}", slot="s", value=str(index),
                                         scope=REPO, source_ids=("c1",))])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(20)))
    assert m.core.status()["identities"] == 20, m.core.status()


def f6_concurrent_property(m):
    def write(index):
        m.core.remember([MemoryCandidate(entity=ENTITY, slot="runtime", value=f"v{index}",
                                         scope=REPO, source_ids=("c1",))])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(8)))
    status = m.core.status()
    assert status["identities"] == 1 and status["revisions"] == 8, status


# ---------------------------------------------------------------- retrieval
def g1_text(m):
    m.mem()
    assert m.core.search("python3.10")["counts"]["CURRENT_CONFIRMED"] == 1


def g2_anchor(m):
    m.mem()
    assert len(m.query(slot=None)["results"]) == 1


def g3_topic(m):
    m.mem(topics=("deploy",))
    m.mem(slot="other", value="unrelated", topics=("misc",), source_ids=("c2",))
    packet = m.core.query(MemoryQuery(topics=("deploy",), with_evidence=False))
    assert len(packet["results"]) == 1 and packet["results"][0]["slot"] == "runtime"


def g4_limit(m):
    for index in range(5):
        m.mem(entity=f"e{index}", slot="s", value=f"v{index}", topics=("bulk",),
              source_ids=("c1",))
    packet = m.core.query(MemoryQuery(topics=("bulk",), limit=2, with_evidence=False))
    assert len(packet["results"]) == 2


def g5_ranking(m):
    m.mem(slot="one", value="alpha alpha alpha")
    m.mem(slot="two", value="alpha beta", source_ids=("c2",))
    top = m.core.search("alpha")["results"][0]
    assert "alpha alpha" in top["value"], top


def g6_search_as_of(m):
    m.mem()
    m.mem(value="python3.12", source_ids=("c2",))
    old = m.core.search("python3.12", window=(None, T1))["results"]
    assert old and old[0]["value"] == "python3.10", old


def g7_empty_search(m):
    try:
        m.core.search("  ")
    except CSMError as error:
        assert "search_text_empty" in str(error), error
        return
    raise AssertionError("empty search accepted")


# ---------------------------------------------------------------- operations
def h1_rebuild(m):
    m.mem()
    before = [row["memory_id"] for row in m.core.search("python3.10")["results"]]
    m.core.rebuild()
    after = [row["memory_id"] for row in m.core.search("python3.10")["results"]]
    assert before == after, (before, after)


def h2_status(m):
    m.mem()
    status = m.core.status()
    assert status["events"] == 3 and status["commits"] == 3, status
    assert status["identities"] == 1 and status["revisions"] == 1, status


def h3_namespace(m):
    try:
        CsmStore(m.db, namespace="other")
    except CSMError as error:
        assert "store_namespace_conflict" in str(error), error
        return
    raise AssertionError("namespace conflict accepted")


def h4_reopen(m):
    m.mem()
    reopened = CSM(CsmStore(m.db, namespace="case"))
    packet = reopened.query(MemoryQuery(entity=ENTITY, slot="runtime", with_evidence=False))
    assert packet["results"][0]["value"] == "python3.10"


def h5_no_projection(m):
    with closing(sqlite3.connect(m.db)) as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "projection" not in tables, tables


def h6_consolidation(m):
    m.mem()
    stats = m.core.consolidate()
    assert stats["identities"] == 1 and stats["state"] == 1, stats


def h7_evidence_off(m):
    m.mem()
    row = m.core.search("python3.10", with_evidence=False)["results"][0]
    assert "evidence" not in row, row


CASES = [
    ("A1", "身份", "首次写入创建身份", a1_first_write),
    ("A2", "身份", "重复观测不产生修订", a2_duplicate),
    ("A3", "身份", "state 原地覆盖", a3_overwrite),
    ("A4", "身份", "event 追加不覆盖", a4_event_append),
    ("A5", "身份", "属性别名解析", a5_alias),
    ("A6", "身份", "decision 推断为 event", a6_event_inference),
    ("A7", "身份", "build_command 推断为 state", a7_state_inference),
    ("A8", "身份", "显式 kind 优先", a8_explicit_kind),
    ("B1", "作用域", "默认实体作用域", b1_default_scope),
    ("B2", "作用域", "仓库之间隔离", b2_repo_isolation),
    ("B3", "作用域", "branch 覆盖 repo", b3_branch_overrides),
    ("B4", "作用域", "精确 branch 不看 repo", b4_exact_hides_repo),
    ("B5", "作用域", "早期 commit 回退 repo", b5_earlier_commit_falls_back),
    ("B6", "作用域", "event 按 origin_scope 可见", b6_event_visible_by_scope),
    ("B7", "作用域", "跨仓库不可见", b7_cross_repo),
    ("C1", "时间", "首次修订前为 UNKNOWN", c1_before_history),
    ("C2", "时间", "两次修订之间取旧值", c2_between),
    ("C3", "时间", "之后取 head", c3_after),
    ("C4", "时间", "at_commit 历史值", c4_commit_historical),
    ("C5", "时间", "at_commit 当前值", c5_commit_current),
    ("C6", "时间", "未知 commit 拒绝", c6_unknown_commit),
    ("C7", "时间", "commit 与 instant 互斥", c7_ambiguous_time),
    ("C8", "时间", "include_history 返回旧值", c8_history),
    ("D1", "证据", "附带来源原文", d1_evidence_text),
    ("D2", "证据", "证据按 700 字符截断", d2_evidence_truncated),
    ("D3", "证据", "未知来源拒绝", d3_missing_source),
    ("D4", "证据", "修订携带 commit", d4_commit_on_revision),
    ("D5", "证据", "event 身份按观测分区", d5_event_partition),
    ("D6", "证据", "metadata 落库", d6_metadata_persisted),
    ("E1", "脱敏", "事件 payload 脱敏", e1_payload),
    ("E2", "脱敏", "候选值脱敏", e2_value),
    ("E3", "脱敏", "metadata 键脱敏", e3_metadata),
    ("E4", "脱敏", "检索结果不含密钥", e4_search),
    ("E5", "脱敏", "脱敏后摘要稳定", e5_digest_stable),
    ("F1", "一致性", "事件幂等", f1_event_idempotent),
    ("F2", "一致性", "事件冲突拒绝", f2_event_conflict),
    ("F3", "一致性", "重复记忆不增修订", f3_duplicate_memory),
    ("F4", "一致性", "expected_revision 冲突", f4_cas),
    ("F5", "一致性", "并发写不同实体", f5_concurrent_entities),
    ("F6", "一致性", "并发写同一属性", f6_concurrent_property),
    ("G1", "检索", "文本检索命中", g1_text),
    ("G2", "检索", "实体锚点查询", g2_anchor),
    ("G3", "检索", "topic 过滤", g3_topic),
    ("G4", "检索", "limit 生效", g4_limit),
    ("G5", "检索", "词频排序", g5_ranking),
    ("G6", "检索", "search 按时间截断", g6_search_as_of),
    ("G7", "检索", "空查询拒绝", g7_empty_search),
    ("H1", "运维", "rebuild 幂等", h1_rebuild),
    ("H2", "运维", "status 计数", h2_status),
    ("H3", "运维", "命名空间冲突拒绝", h3_namespace),
    ("H4", "运维", "重开存储保留状态", h4_reopen),
    ("H5", "运维", "不再创建 projection", h5_no_projection),
    ("H6", "运维", "consolidation 审计", h6_consolidation),
    ("H7", "运维", "可按需关闭证据", h7_evidence_off),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "benchmarks" / "results" /
                        f"csm-capability-matrix-{time.strftime('%Y%m%d')}.json")
    args = parser.parse_args()
    records, by_category = [], {}
    for case_id, category, name, function in CASES:
        with tempfile.TemporaryDirectory() as directory:
            try:
                function(Matrix(Path(directory)))
                status, detail = "pass", ""
            except Exception as error:  # one failed case never stops the matrix
                status = "fail"
                detail = f"{type(error).__name__}: {error}"
                if not isinstance(error, AssertionError):
                    detail = f"{detail} | {traceback.format_exc(limit=2).splitlines()[-1]}"
        bucket = by_category.setdefault(category, {"pass": 0, "fail": 0})
        bucket[status] += 1
        records.append({"id": case_id, "category": category, "case": name,
                        "status": status, **({"detail": detail} if detail else {})})
        print(f"{case_id} {status.upper():4} {category} / {name}"
              + (f" :: {detail}" if detail else ""), flush=True)
    passed = sum(1 for record in records if record["status"] == "pass")
    summary = {"total": len(records), "passed": passed, "failed": len(records) - passed,
               "by_category": by_category, "cases": records}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("total", "passed", "failed",
                                                    "by_category")}, ensure_ascii=False))
    raise SystemExit(0 if passed == len(records) else 1)


if __name__ == "__main__":
    main()
