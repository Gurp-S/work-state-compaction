"""用修复后的写入链路重建一份记忆库（只写不答）。

    WSC_CSM_EXTRACT_FIX=1 py -3.11 benchmarks/rebuild_db.py --until 179 --out benchmarks/results/wsfix.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import csm_public_exam as exam  # noqa: E402
from wsc.csm.cem import slot_naming  # noqa: E402
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate  # noqa: E402

HISTORY = Path(".bench/memory-system-benchmark/demo/histories/PUB01.jsonl")
PERSONA = "PUB01"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", type=int, default=179)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/results/wsfix.db"))
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()

    rows = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()]
    chat = exam.Chat()
    service = CSM(CsmStore(str(args.out), namespace=f"public-exam:{PERSONA}"))
    entities: list[str] = []
    slots: dict[str, set[str]] = {}
    written = 0

    for number in range(1, args.until + 1):
        turn = rows[number - 1]
        event_id = f"{PERSONA}/turn/{number:04d}"
        service.ingest([Event(id=event_id, source_type="chat",
                              payload={"user": turn["用户消息"], "assistant": turn["助手回复"]},
                              observed_at=turn["逻辑时间"])])
        try:
            candidates = exam.extract(chat, turn, entities)
        except RuntimeError:
            print(f"{event_id}: extract_failed", flush=True)
            continue
        if not candidates:
            continue
        for item in candidates:
            item["slot"] = slot_naming.normalize(item["slot"], slots.setdefault(item["entity"], set()))
        service.remember([MemoryCandidate(entity=item["entity"], slot=item["slot"], value=item["value"],
                                          contexts=(), topics=tuple(item["topics"]), source_ids=(event_id,))
                          for item in candidates], producer="benchmark-adapter")
        for item in candidates:
            slots[item["entity"]].add(item["slot"])
            if item["entity"] not in entities:
                entities.append(item["entity"])
        written += len(candidates)
        print(f"{event_id}: +{len(candidates)}", flush=True)

    print(f"turns={args.until} facts={written} db={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
