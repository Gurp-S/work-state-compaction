"""Per-question four-stage attribution for Locomo-Plus.

For every question it records whether the correct memory

    db        exists anywhere in the store
    candidate entered the candidate pool (search + entity query, before truncation)
    topk      survived ranking and entered the final Top-K
    assembly  was actually rendered into the prompt handed to the answer model

Run it against the DB of a finished QA run; it replays retrieval only, no LLM calls:

    py -3.11 benchmarks/locomo_stage_probe.py <db> <records.json> <out.json>
"""
from __future__ import annotations

import json
import math
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import csm_locomo_plus as adapter  # noqa: E402
from csm_locomo_plus import BENCH, _tokens  # noqa: E402
from wsc.csm import CSM, CsmStore, MemoryQuery  # noqa: E402

TOP_K = 12


def gold_rule(gold: str) -> tuple[set[str], int]:
    """Tokens of the reference answer, and how many must appear for a hit.

    Short answers ("7 May 2023") must match every token: a single shared word would
    otherwise turn dozens of unrelated memories into "gold", which inflates every stage.
    """
    tokens = _tokens(gold)
    if len(tokens) <= 3:
        return tokens, len(tokens)
    return tokens, max(2, round(len(tokens) * 0.6))


def gold_memories(values: dict[str, str], tokens: set[str], need: int) -> set[str]:
    """IDF-weighted coverage: a token shared by most memories ("2023") must not make them gold.

    Without this, stamping a session date onto every value turns that whole session into
    "correct memories" and every later stage looks broken.
    """
    if not tokens:
        return set()
    from locomo_rank import document_frequency
    frequency = document_frequency(values)
    total = max(1, len(values))
    weight = {token: math.log(1 + total / (1 + frequency.get(token, 0))) for token in tokens}
    mass = sum(weight.values()) or 1.0
    hits = set()
    for memory_id, value in values.items():
        lowered = value.lower()
        covered = sum(weight[token] for token in tokens if token in lowered)
        if covered / mass >= 0.6:
            hits.add(memory_id)
    return hits


def replay(service, entities: list[str], question: str) -> tuple[dict, list[str]]:
    """Same retrieval shape as the benchmark: wide pool, then local rerank, then Top-K."""
    pool: dict[str, dict] = {}
    for item in service.search(question, limit=40, diverse=True)["results"]:
        pool[item["memory_id"]] = item
    lowered = question.lower()
    for name in entities:
        if name and name.split()[0].lower() in lowered:
            for item in service.query(MemoryQuery(entity=name, limit=60))["results"]:
                pool.setdefault(item["memory_id"], item)
    query_tokens = _tokens(question)

    def score(item: dict) -> float:
        text = _tokens(" ".join(str(item.get(k) or "") for k in ("entity", "slot", "value")))
        return len(query_tokens & text) + 0.15 * float(item.get("score") or 0)

    ranked = sorted(pool.values(), key=score, reverse=True)[:TOP_K]
    return pool, [item["memory_id"] for item in ranked]


def replay_faithful(service, entities: list[str], question: str) -> tuple[dict, list[str]]:
    """Use the adapter's own path, so the probe measures the run rather than a lookalike."""
    pool = {item["memory_id"]: item for item in adapter.candidate_pool(service, question, entities)}
    return pool, [item["memory_id"] for item in adapter.retrieve_wide(service, question, entities)]


def classify(row: dict) -> str:
    if not row["gold_tokens"]:
        return "no_gold_answer"
    if not row["db"]:
        return "extraction_miss"
    if not row["candidate"]:
        return "candidate_miss"
    if not row["topk"]:
        return "ranking_cut"
    if row["missing_multi"]:
        return "partial_multihop"
    if row["stale"]:
        return "stale_version"
    if row["conflict"]:
        return "conflict"
    return "reasoning_or_format"


def main() -> None:
    db = Path(sys.argv[1])
    records_path = Path(sys.argv[2])
    out = Path(sys.argv[3])
    work = Path(".bench/tmp/stage-replay.db")
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(db, work)

    adapter._DB_PATH = str(db)
    records = json.loads(records_path.read_text(encoding="utf-8"))["records"]
    questions = json.loads((BENCH / "data" / "locomo10.json").read_text(encoding="utf-8"))[0]["qa"]
    con = sqlite3.connect(f"file:{work}?mode=ro", uri=True)
    values, status = {}, {}
    for memory_id, data in con.execute("select memory_id, data from revisions"):
        payload = json.loads(data)
        values[memory_id] = str(payload.get("value") or "")
        status[memory_id] = str(payload.get("status") or "")
    slots: dict[str, tuple[str, str]] = {}
    for memory_id, entity, slot in con.execute("select memory_id, entity, slot from identities"):
        slots[memory_id] = (entity, slot)
    entities = sorted({entity for entity, _slot in slots.values()})
    con.close()

    service = CSM(CsmStore(work, namespace="locomo0"))
    rows = []
    for question, record in zip(questions, records):
        tokens, need = gold_rule(str(question.get("answer") or ""))
        gold = gold_memories(values, tokens, need)
        pool, top = replay_faithful(service, entities, question["question"])
        in_pool, in_top = gold & set(pool), gold & set(top)
        # 同一事实常有多条近义记忆：按 (entity, slot) 归并，避免"全部命中才算齐"的虚高。
        gold_pairs = {slots.get(memory_id, ("", "")) for memory_id in gold}
        covered_pairs = {slots.get(memory_id, ("", "")) for memory_id in in_top}
        pairs = [slots.get(memory_id, ("", "")) for memory_id in top]
        row = {
            "question": question["question"],
            "category": record["category"],
            "verdict": record["judge"]["label"],
            "gold_tokens": sorted(tokens),
            "db": sorted(gold),
            "candidate": sorted(in_pool),
            "topk": sorted(in_top),
            "recorded_retrieved": record["retrieved"],
            "replay_matches_run": set(top) == set(record["retrieved"]),
            "gold_pairs": sorted("/".join(pair) for pair in gold_pairs),
            "covered_pairs": sorted("/".join(pair) for pair in covered_pairs),
            "missing_multi": len(covered_pairs) < len(gold_pairs),
            "stale": any(status.get(memory_id) == "retracted" for memory_id in in_top),
            "conflict": len({p for p in pairs if p[0]}) != len({p[0] for p in pairs if p[0]}),
        }
        row["stage"] = classify(row)
        rows.append(row)

    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    wrong = [row for row in rows if row["verdict"] != "correct"]
    buckets: dict[str, int] = {}
    for row in wrong:
        buckets[row["stage"]] = buckets.get(row["stage"], 0) + 1
    print(f"questions {len(rows)}  wrong {len(wrong)}  replay_match "
          f"{sum(1 for row in rows if row['replay_matches_run'])}/{len(rows)}")
    for stage, count in sorted(buckets.items(), key=lambda pair: -pair[1]):
        print(f"  {stage:22}{count:>4}")
    print("\nby category:")
    for category in ("single-hop", "temporal", "multi-hop", "common-sense", "adversarial"):
        rows_ = [row for row in wrong if row["category"] == category]
        if not rows_:
            continue
        detail = " ".join(f"{stage}={sum(1 for row in rows_ if row['stage'] == stage)}"
                          for stage in sorted({row["stage"] for row in rows_}))
        print(f"  {category:14}{len(rows_):>4}  {detail}")


if __name__ == "__main__":
    main()
