"""写入侧探针：一道题答错，是原文里就没有、根本没抽出来、还是抽出来绑错了身份。

只读：db 里的 events 提供原始对话轮，revisions 提供写进库的事实。不调用模型。

三个桶：
  source_lacks   evidence 原文里就没有答案词元——数据集/证据标注问题，抽取再改也没用
  dropped        evidence 原文有，库里任何记忆都不覆盖——抽取真的漏了
  misbound      库里某条记忆覆盖了答案词元，但不来自 evidence 会话——抽出来了却挂错来源
  written_ok    来自 evidence 会话的记忆覆盖了答案词元——写入没问题，错在检索/作答
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import locomo_rank as ranker  # noqa: E402

COVERAGE = 0.6
STOP = {"the", "and", "for", "with", "that", "this", "from", "have", "has", "was", "were",
        "been", "being", "his", "her", "she", "him", "they", "them", "their", "there",
        "what", "when", "where", "who", "how", "did", "does", "do", "is", "are", "in",
        "on", "at", "to", "of", "a", "an", "it", "its", "as", "by", "or", "be", "not"}


def _terms(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9']+", str(text).lower()) if w not in STOP]
    return [w for w in words if len(w) > 1]


def _idf(values: list[str]) -> dict[str, float]:
    total = len(values) or 1
    df: Counter = Counter()
    for value in values:
        df.update(set(_terms(value)))
    return {word: max(0.2, __import__("math").log((total + 1) / (count + 1)) + 1)
            for word, count in df.items()}


def _coverage(gold: list[str], text: str, idf: dict[str, float]) -> float:
    if not gold:
        return 0.0
    present = set(_terms(text))
    weight = sum(idf.get(w, 1.0) for w in gold)
    hit = sum(idf.get(w, 1.0) for w in gold if w in present)
    return hit / weight if weight else 0.0


def load_turns(db: Path) -> dict[str, dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    turns: dict[str, dict] = {}
    for event_id, payload in con.execute("select id, data from events").fetchall():
        data = json.loads(payload or "{}")
        for turn in data.get("turns") or []:
            dia = turn.get("dia_id")
            if dia:
                turns[dia] = {"session": event_id, "speaker": turn.get("speaker", ""),
                              "text": turn.get("text", ""), "date": data.get("date", "")}
    return turns


def load_memories(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("select memory_id, data from revisions").fetchall()
    memories = []
    for memory_id, data in rows:
        payload = json.loads(data)
        memories.append({"memory_id": memory_id,
                         "value": payload.get("value", ""),
                         "sources": payload.get("source_refs") or []})
    return memories


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("records", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results" / "write-probe.json")
    args = parser.parse_args()

    turns = load_turns(args.db)
    memories = load_memories(args.db)
    idf = _idf([m["value"] for m in memories])
    records = json.loads(args.records.read_text(encoding="utf-8"))["records"]
    dataset = json.loads((ROOT / ".bench" / "Locomo-Plus" / "data" / "locomo10.json")
                         .read_text(encoding="utf-8"))
    evidence_by_question = {item["question"]: item.get("evidence") or []
                            for item in (dataset[0].get("qa") or [])}
    for record in records:
        record.setdefault("evidence", evidence_by_question.get(record.get("question"), []))
        record.setdefault("answer", record.get("gold", ""))
        judge = str(record.get("judge") or "")
        found = re.search(r"label'?:\s*'(\w+)'", judge)
        record.setdefault("verdict", found.group(1) if found else record.get("verdict"))

    buckets: Counter = Counter()
    examples: dict[str, list[dict]] = {}
    for record in records:
        gold = _terms(record.get("answer") or record.get("gold") or "")
        evidence = record.get("evidence") or []
        source_text = " ".join(
            f"{turns[dia]['date']} {turns[dia]['text']}" for dia in evidence if dia in turns)
        sessions = {turns[dia]["session"] for dia in evidence if dia in turns}

        source_has = _coverage(gold, source_text, idf) >= COVERAGE
        same_session = [m for m in memories if sessions & set(m["sources"])
                        and _coverage(gold, m["value"], idf) >= COVERAGE]
        anywhere = [m for m in memories if _coverage(gold, m["value"], idf) >= COVERAGE]

        if not source_has:
            bucket = "source_lacks"
        elif same_session:
            bucket = "written_ok"
        elif anywhere:
            bucket = "misbound"
        else:
            bucket = "dropped"
        buckets[bucket] += 1
        examples.setdefault(bucket, []).append({
            "question": record.get("question", "")[:120],
            "answer": record.get("answer", ""),
            "verdict": record.get("verdict"),
            "evidence": evidence,
            "source": source_text[:200],
            "memory": (same_session or anywhere or [{}])[0].get("value", "")[:160],
        })

    verdicts = Counter(record.get("verdict") for record in records)
    print(f"questions {len(records)}  verdicts {dict(verdicts)}")
    print(f"memories {len(memories)}  turns {len(turns)}")
    for bucket in ("written_ok", "dropped", "misbound", "source_lacks"):
        print(f"  {bucket:12} {buckets[bucket]:4}")

    print("\nwrong answers only:")
    wrong = Counter()
    for record in records:
        if record.get("verdict") == "correct":
            continue
        gold = _terms(record.get("answer") or record.get("gold") or "")
        evidence = record.get("evidence") or []
        source_text = " ".join(
            f"{turns[dia]['date']} {turns[dia]['text']}" for dia in evidence if dia in turns)
        sessions = {turns[dia]["session"] for dia in evidence if dia in turns}
        if _coverage(gold, source_text, idf) < COVERAGE:
            wrong["source_lacks"] += 1
        elif any(sessions & set(m["sources"]) and _coverage(gold, m["value"], idf) >= COVERAGE
                 for m in memories):
            wrong["written_ok"] += 1
        elif any(_coverage(gold, m["value"], idf) >= COVERAGE for m in memories):
            wrong["misbound"] += 1
        else:
            wrong["dropped"] += 1
    for bucket, count in wrong.most_common():
        print(f"  {bucket:12} {count:4}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"all": dict(buckets), "wrong": dict(wrong),
                                    "examples": examples}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
