"""把写入侧修复补进一份既有记忆库：只补抽取漏掉的条目，其余条目原样不动。

用法：
    WSC_CSM_EXTRACT_FIX=1 py -3.11 benchmarks/write_side_fix.py --db benchmarks/results/ab2-off.db \
        --out benchmarks/results/ext-fix.db

做法：逐轮重跑抽取（带重试 + 改口规则），只把"这一轮库里还没有"的条目写进副本库。
这样 A/B 的差异只来自写入侧，检索、预算、图规模全部保持不变。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csm_public_exam as exam  # noqa: E402
from wsc.csm import CSM, CsmStore, MemoryCandidate  # noqa: E402

HISTORY = Path(".bench/memory-system-benchmark/demo/histories/PUB01.jsonl")
PERSONA = "PUB01"
CORRECTION = re.compile(r"其实|不是|改成|改回|纠正|说错|记错|应该是")


def existing_facts(db_path: Path) -> tuple[dict[str, dict[tuple[str, str], str]], dict[str, str]]:
    """event_id -> {(entity, slot): value}，以及 memory_id -> entity。"""
    con = sqlite3.connect(db_path)
    values = {}
    for memory_id, data in con.execute("select memory_id, data from projection"):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        try:
            values[memory_id] = str(json.loads(data).get("value") or "")
        except json.JSONDecodeError:
            values[memory_id] = ""
    facts: dict[str, dict[tuple[str, str], str]] = {}
    for data, in con.execute("select data from identities"):
        if isinstance(data, bytes):
            data = data.decode("utf-8", "ignore")
        try:
            row = json.loads(data)
        except json.JSONDecodeError:
            continue
        slot = (str(row.get("entity") or ""), str(row.get("slot") or ""))
        value = values.get(str(row.get("memory_id")), "")
        for event_id in row.get("identity_evidence") or []:
            facts.setdefault(str(event_id), {})[slot] = value
    return facts, values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("benchmarks/results/ab2-off.db"))
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/ext-fix.db"))
    args = parser.parse_args()

    if not args.out.exists():
        shutil.copyfile(args.db, args.out)

    rows = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()]
    # 对副本库求差集：重跑时已经补过的条目不会重复写入。
    facts, _ = existing_facts(args.out)
    ingested = {int(match) for event in facts for match in re.findall(rf"{PERSONA}/turn/(\d+)", event)}
    entities = sorted({entity for group in facts.values() for entity, _ in group})

    chat = exam.Chat()
    service = CSM(CsmStore(str(args.out), namespace=f"public-exam:{PERSONA}"))

    added = 0
    touched = 0
    for number in sorted(ingested):
        turn = rows[number - 1]
        event_id = f"{PERSONA}/turn/{number:04d}"
        known = facts.get(event_id, {})
        try:
            extracted = exam.extract(chat, turn, entities)
        except RuntimeError:
            # 单轮抽取耗尽重试不该中断整库回填；记下来，下次重跑会再试这一轮。
            print(f"{event_id}: extract_failed", flush=True)
            continue
        # 只补两类：这一轮从未写过的属性；或用户明确改口时的同属性新值。
        # 换个说法的重复事实不补，否则重跑会把同一件事写成多条。
        correcting = bool(CORRECTION.search(str(turn.get("用户消息") or "")))
        candidates = []
        for item in extracted:
            entity = str(item["entity"]).strip()
            slot = str(item["slot"]).strip()
            value = str(item["value"]).strip()
            if (entity, slot) not in known:
                candidates.append(item)
            elif correcting and known[(entity, slot)] != value:
                candidates.append(item)
        if not candidates:
            continue
        service.remember([MemoryCandidate(entity=item["entity"], slot=item["slot"], value=item["value"],
                                          contexts=(), topics=tuple(item["topics"]), source_ids=(event_id,))
                          for item in candidates], producer="benchmark-adapter")
        added += len(candidates)
        touched += 1
        print(f"{event_id}: +{len(candidates)}", flush=True)

    print(f"turns_scanned={len(ingested)} turns_touched={touched} facts_added={added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
