"""Side-path comparison of evidence export strategies; no production code touched.

Every strategy writes the exact bytes the real export produced, into a fresh
directory, and is timed on wall clock and CPU. Run with:

    PYTHONPATH=src python experiments/export_strategies.py --events 600 --rounds 5
"""
import argparse
import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

from wsc import WSC, Store, Selection, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc import evidence


def build_session(count, root):
    adapter = CodexCheckpointAdapter()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pipeline_profile import make_items

    events = adapter.import_items(make_items(count), thread_id="strategies")
    core = WSC(Store(root / "state.db", session_id="s", workspace=str(root)), access=lambda *_: True)
    core.ingest(events)
    core.presented_many([(f"present:{event.call_id}", (event.id,), "receiver")
                         for event in events if event.kind == "result"])
    snapshot = core.capture()
    core.material(snapshot)
    selectable = tuple(row["id"] for row in snapshot.events if row["kind"] != "opaque")
    view = core.prepare(snapshot, Selection(source_ids=selectable), producer="strategies",
                        limits=Limits(max_view_bytes=8_000_000, max_material_bytes=32_000_000))
    return core, adapter, view


def collect_payloads(directory):
    """The exact object bytes the real export produced, keyed by file name."""
    items = []
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            items.append((path.name, path.read_bytes()))
    return items


def write_plain(root, items):
    for name, payload in items:
        evidence.write_once(root / name, payload)


def write_no_precheck(root, items):
    # Same writer without the leading link_like() stat; O_EXCL already refuses
    # an existing entry and the conflict branch still rejects a link leaf.
    import os
    for name, payload in items:
        path = root / name
        try:
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise


def write_no_sync(root, items):
    for name, payload in items:
        evidence.write_once(root / name, payload, sync=False)


def write_threads(root, items, workers=8):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda item: evidence.write_once(root / item[0], item[1]), items))


def write_bundle(root, items):
    """One file, one fsync: index line followed by the payloads."""
    index = []
    offset = 0
    body = bytearray()
    for name, payload in items:
        index.append({"name": name, "offset": offset, "length": len(payload),
                      "sha256": sha256(payload).hexdigest()})
        body += payload
        offset += len(payload)
    header = json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path = root / "bundle.wscb"
    with path.open("xb") as stream:
        stream.write(len(header).to_bytes(8, "big"))
        stream.write(header)
        stream.write(body)
        stream.flush()
        import os
        os.fsync(stream.fileno())


def measure(writer, items, rounds):
    wall, cpu = [], []
    for _ in range(rounds):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start_wall, start_cpu = time.perf_counter(), time.process_time()
            writer(root, items)
            wall.append(time.perf_counter() - start_wall)
            cpu.append(time.process_time() - start_cpu)
    return {"wall": round(statistics.median(wall), 4), "cpu": round(statistics.median(cpu), 4)}


def measure_pragma(items, rounds):
    """Does mmap_size / cache_size change anything for a database this small?"""
    from wsc.store import Store
    import sqlite3
    from wsc import events as events_module

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Store(root / "state.db", session_id="s", workspace=str(root))
        adapter = CodexCheckpointAdapter()
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pipeline_profile import make_items
        core = WSC(store, access=lambda *_: True)
        core.ingest(adapter.import_items(make_items(600), thread_id="p"))

        def run(pragmas):
            samples = []
            for _ in range(rounds):
                with store.connect() as db:
                    for statement in pragmas:
                        db.execute(statement)
                    start = time.perf_counter()
                    events_module.rows(db)
                    samples.append(time.perf_counter() - start)
            return round(statistics.median(samples), 5)

        return {"default": run([]), "tuned": run(["PRAGMA mmap_size=268435456",
                                                  "PRAGMA cache_size=-65536",
                                                  "PRAGMA temp_store=MEMORY"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=600)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        core, adapter, view = build_session(args.events, root)
        core.stage(view, directory=root / "export", adapter=adapter)
        items = collect_payloads(root / "export")
        baseline = measure(write_plain, items, args.rounds)
        result = {
            "format": "wsc.export_strategies/1",
            "objects": len(items),
            "bytes": sum(len(payload) for _, payload in items),
            "rounds": args.rounds,
            "strategies": {
                "baseline": baseline,
                "no_precheck_stat": measure(write_no_precheck, items, args.rounds),
                "no_sync": measure(write_no_sync, items, args.rounds),
                "threads": measure(lambda r, i: write_threads(r, i, args.workers), items, args.rounds),
                "bundle_one_file": measure(write_bundle, items, args.rounds),
            },
            "pragma_rows": measure_pragma(items, args.rounds),
        }
        for name, value in result["strategies"].items():
            if name != "baseline":
                value["wall_ratio"] = round(value["wall"] / baseline["wall"], 3)
                value["cpu_ratio"] = round(value["cpu"] / baseline["cpu"], 3)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
