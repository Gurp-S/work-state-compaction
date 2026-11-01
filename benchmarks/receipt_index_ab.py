"""Cost of one source-index lookup, and how much of it is schema upkeep.

``is_delivered`` runs ``_ensure_receipt_aux`` on every call, so the per-call
price is (schema upkeep + cursor checks + one point lookup).  This splits the
three so an optimisation targets the part that actually costs.

Run: ``py -3.11 benchmarks/receipt_index_ab.py``
"""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc import WSC, Store, events, integrity
from wsc.contracts import Event

SOURCES = 2000
CALLS = 500


def build(root: Path) -> WSC:
    core = WSC(Store(root / "state.db", session_id="ab", workspace=str(root)),
               access=lambda *a: True)
    ids = core.ingest([Event(f"e{i}", "observation", {}, text="x" * 32) for i in range(SOURCES)])
    with core.store.transaction() as db:
        integrity.install_receipts(db)
        events.presented(db, "r0", tuple(ids), "model")
        events.presented(db, "r1", (ids[0],), "model")
    return core


def timed(fn) -> float:
    samples = []
    for _ in range(CALLS):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples) * 1e6


def main() -> None:
    temp = tempfile.TemporaryDirectory(prefix="wsc-bench-")
    core = build(Path(temp.name))
    original = integrity._ensure_receipt_aux
    rows = {}

    with core.store.connect() as db:
        rows["lookup_us"] = timed(lambda: integrity.is_delivered(db, "e1"))
        rows["aux_us"] = timed(lambda: integrity._ensure_receipt_aux(db))
        rows["verify_us"] = timed(lambda: integrity.verify_receipts(db))
        integrity._ensure_receipt_aux = lambda db: None
        try:
            rows["lookup_without_aux_us"] = timed(lambda: integrity.is_delivered(db, "e1"))
        finally:
            integrity._ensure_receipt_aux = original

    # The one-time maintenance path, timed the way its contract requires it to
    # run: inside a transaction, so it pays one commit instead of one per row.
    with core.store.transaction() as db:
        started = time.perf_counter()
        report = integrity.rebuild_receipt_index(db)
        rows["rebuild_ms"] = (time.perf_counter() - started) * 1000

    print(f"sources={SOURCES} receipts=2 calls={CALLS}")
    for key, value in rows.items():
        print(f"{key:24s} {value:10.1f}")
    print("rebuilt rows", report["rebuilt"])
    temp.cleanup()


if __name__ == "__main__":
    main()
