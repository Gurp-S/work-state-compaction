"""A/B: per-release full receipt audit (before) vs full-audit checkpoint (after).

Before: every ``stage()`` called ``integrity.audit_receipts(db)`` and re-hashed the
whole receipt history.  After: ``publication.stage()`` calls
``audit_cache.audit_receipts_cached()``, which re-audits only when the chain head,
receipt count or protocol version moved.

Run: ``py -3.11 benchmarks/audit_cache_ab.py``
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wsc import WSC, Store, Selection, events, integrity
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.audit_cache import audit_receipts_cached
from wsc.contracts import Event


def build(root: Path, receipts: int) -> WSC:
    core = WSC(Store(root / "state.db", session_id="ab", workspace=str(root)),
               access=lambda *a: True)
    ids = core.ingest([Event(f"e{i}", "observation", {}, text="x" * 64) for i in range(receipts)])
    with core.store.transaction() as db:
        integrity.install_receipts(db)
        for i in range(receipts):
            events.presented(db, f"r{i}", (ids[i],), "model")
    return core


def before_audit(core: WSC) -> dict:
    with core.store.transaction() as db:
        report = integrity.audit_receipts(db)
    return {**report, "reused": False, "scope": "full", "integrity_version":
            integrity.RECEIPT_INTEGRITY_VERSION, "checkpoint_count": None, "reason": None}


def legacy_audit(db, *, session_id: str, anchor: str | None = None) -> dict:
    """The pre-cache publication call: an unconditional full audit, same txn."""
    report = integrity.audit_receipts(db)
    return {**report, "reused": False, "scope": "full", "checkpoint_count": None, "reason": None,
            "integrity_version": integrity.RECEIPT_INTEGRITY_VERSION}


def after_audit(core: WSC) -> dict:
    with core.store.transaction() as db:
        return audit_receipts_cached(db, session_id="ab")


def measure(fn, rounds: int) -> tuple[float, dict]:
    samples, report = [], None
    for _ in range(rounds):
        started = time.perf_counter()
        report = fn()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples), report


def macro(core: WSC, rounds: int, adapter, directory: Path, legacy: bool) -> float:
    samples = []
    for _ in range(rounds):
        view = core.prepare(core.capture(), Selection(), producer="ab")
        started = time.perf_counter()
        if legacy:
            with mock.patch("wsc.publication.audit_cache.audit_receipts_cached",
                            side_effect=legacy_audit):
                operation = core.stage(view, directory=directory, adapter=adapter)
        else:
            operation = core.stage(view, directory=directory, adapter=adapter)
        samples.append((time.perf_counter() - started) * 1000)
        core.discard(operation)
    return statistics.median(samples)


def main() -> dict:
    adapter = CodexCheckpointAdapter()
    rows = []
    with tempfile.TemporaryDirectory(prefix="wsc-ab-") as temp:
        base = Path(temp)
        for receipts in (100, 1000, 3000):
            root = base / f"n{receipts}"
            root.mkdir()
            core = build(root, receipts)
            cold_ms, cold_report = measure(lambda: before_audit(core), 1)
            warm_before_ms, before_report = measure(lambda: before_audit(core), 15)
            first_ms, first_report = measure(lambda: after_audit(core), 1)
            warm_after_ms, after_report = measure(lambda: after_audit(core), 15)
            stage_before_ms = macro(core, 5, adapter, root / "before", legacy=True)
            stage_after_ms = macro(core, 5, adapter, root / "after", legacy=False)
            rows.append({
                "receipts": receipts,
                "audit_before_ms": round(warm_before_ms, 3),
                "audit_after_ms": round(warm_after_ms, 3),
                "audit_speedup": round(warm_before_ms / max(warm_after_ms, 1e-9), 1),
                "stage_before_ms": round(stage_before_ms, 2),
                "stage_after_ms": round(stage_after_ms, 2),
                "stage_speedup": round(stage_before_ms / max(stage_after_ms, 1e-9), 2),
                "scanned_before": before_report["scanned"],
                "scanned_after": after_report["scanned"],
                "cached_hit": after_report["reused"],
                "first_release_ms": round(first_ms, 2),
                "cold_scan_ms": round(cold_ms, 2),
            })
            print(f"n={receipts} ok={before_report['ok']}/{after_report['ok']} "
                  f"cold_report_ok={cold_report['ok']} first_report_ok={first_report['ok']}")
    print(json.dumps(rows, indent=2))
    return {"rows": rows}


if __name__ == "__main__":
    main()


