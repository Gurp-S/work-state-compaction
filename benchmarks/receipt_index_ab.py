"""Cost of the receipt paths at 1k / 10k / 100k receipts, one source reused.

Every receipt in this fixture names ``s0``, so ``s0`` is the high-duplication
case: the number of receipts that mention it grows with the scale, which is what
the lookup has to stay independent of.

Metrics, and what each one measures:

  lookup_median/p95   ``is_delivered(s0, verified=True)``: schema-upkeep fast
                      path, index-coverage check and one JOIN.  It does not
                      re-hash receipts, so it is the cost a caller pays per
                      source, not the cost of an audit.
  lookup_miss_median  the same call for a source that was never presented.
  statements          SQL statements executed by one lookup call, counted with
                      ``set_trace_callback``; this is the number that must not
                      grow with the number of receipts naming the source.
  incremental_median  ``verify_receipts()`` with nothing new appended.
  full_audit_median   ``verify_receipts(full=True)``: re-hashes every receipt.
  rebuild_op_median   ``rebuild_receipt_index()`` alone, with the transaction
                      already open (the operation itself).
  rebuild_e2e_median  the same rebuild inside its own BEGIN..COMMIT, so it
                      includes the commit the contract requires.

Audits are timed inside a transaction: they are used that way (publication and
``audit_receipts_cached`` run them in the caller's transaction), and timing them
in autocommit would add one fsync per repeat rather than measure the audit.

Run: ``py -3.11 benchmarks/receipt_index_ab.py``
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc import WSC, Store, integrity
from wsc.contracts import Event

SCALES = tuple(int(value) for value in os.environ.get("WSC_BENCH_SCALES", "1000,10000,100000").split(","))
LOOKUP_CALLS = int(os.environ.get("WSC_BENCH_LOOKUP_CALLS", "200"))
AUDIT_REPEATS = int(os.environ.get("WSC_BENCH_AUDIT_REPEATS", "3"))
REBUILD_REPEATS = int(os.environ.get("WSC_BENCH_REBUILD_REPEATS", "5"))


def build(root: Path, scale: int) -> WSC:
    core = WSC(Store(root / "state.db", session_id="bench", workspace=str(root)),
               access=lambda *a: True)
    core.ingest([Event("s0", "observation", {}, text="hot"),
                 Event("s1", "observation", {}, text="other")])
    receipts = [(f"r{number}",
                 json.dumps({"source_ids": ["s0"] if number % 2 else ["s0", "s1"],
                             "receiver": "model"}))
                for number in range(scale)]
    with core.store.transaction() as db:
        integrity.install_receipts(db)
        db.executemany("INSERT INTO presentations VALUES (?,?)", receipts)
        integrity.advance_receipts(db)
    return core


def spread(times: list[float]) -> tuple[float, float]:
    times.sort()
    p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
    return statistics.median(times), p95


def lookups(db, source: str, calls: int = LOOKUP_CALLS) -> tuple[float, float]:
    for _ in range(20):  # warm the schema-upkeep fast path and the page cache
        integrity.is_delivered(db, source, verified=True)
    times = []
    for _ in range(calls):
        started = time.perf_counter()
        integrity.is_delivered(db, source, verified=True)
        times.append(time.perf_counter() - started)
    return spread(times)


def statements(db, source: str) -> int:
    seen: list[str] = []
    db.set_trace_callback(seen.append)
    try:
        integrity.is_delivered(db, source, verified=True)
    finally:
        db.set_trace_callback(None)
    return len(seen)


def timed(fn, repeats: int) -> float:
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        times.append(time.perf_counter() - started)
    return statistics.median(times)


def main() -> None:
    print(f"scales={SCALES} lookup_calls={LOOKUP_CALLS} "
          f"audit_repeats={AUDIT_REPEATS} rebuild_repeats={REBUILD_REPEATS}")
    for scale in SCALES:
        temp = tempfile.TemporaryDirectory(prefix=f"wsc-bench-{scale}-")
        try:
            core = build(Path(temp.name), scale)
            with core.store.connect() as db:
                hit, hit_p95 = lookups(db, "s0")
                miss, _ = lookups(db, "absent")
                used = statements(db, "s0")
                candidates = db.execute("SELECT COUNT(*) FROM wsc_receipt_sources_v1 "
                                        "WHERE source_id='s0'").fetchone()[0]
                incremental = timed(lambda: integrity.verify_receipts(db), 5)
                full = timed(lambda: integrity.verify_receipts(db, full=True), AUDIT_REPEATS)

            with core.store.transaction() as db:
                op = timed(lambda: integrity.rebuild_receipt_index(db), REBUILD_REPEATS)

            def end_to_end() -> None:
                with core.store.transaction() as db:
                    integrity.rebuild_receipt_index(db)

            e2e = timed(end_to_end, REBUILD_REPEATS)
            print(f"scale={scale:<7d} candidates={candidates:<7d} statements={used:<3d} "
                  f"lookup_median_us={hit * 1e6:8.1f} lookup_p95_us={hit_p95 * 1e6:8.1f} "
                  f"lookup_miss_median_us={miss * 1e6:8.1f} "
                  f"incremental_median_ms={incremental * 1e3:8.3f} "
                  f"full_audit_median_ms={full * 1e3:8.1f} "
                  f"rebuild_op_median_ms={op * 1e3:8.1f} "
                  f"rebuild_e2e_median_ms={e2e * 1e3:8.1f}")
        finally:
            temp.cleanup()


if __name__ == "__main__":
    main()
