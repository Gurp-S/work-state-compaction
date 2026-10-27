"""End-to-end pipeline timing over a synthetic native session; no model calls.

Phases are timed separately so a change can be attributed: ingest, capture,
material, prepare, stage, install. Use --profile to print the hot functions.
"""
import argparse
import json
import statistics
import sys
import tempfile
import time
import cProfile
import pstats
from pathlib import Path

from wsc import WSC, Store, Selection, Limits
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost
from wsc.contracts import HostReceipt


def make_items(count):
    items = [{"type": "message", "role": "system",
              "content": [{"type": "input_text", "text": "session policy " * 12}]}]
    for index in range(count):
        branch = index % 5
        if branch == 0:
            items.append({"type": "message", "role": "user",
                          "content": [{"type": "input_text", "text": f"task {index} " + "detail " * 60}]})
        elif branch == 1:
            items.append({"type": "function_call", "name": "shell", "call_id": f"call-{index}",
                          "arguments": json.dumps({"command": f"inspect {index}"})})
        elif branch == 2:
            items.append({"type": "function_call_output", "call_id": f"call-{index - 1}",
                          "output": f"result {index} " + "row " * 120})
        elif branch == 3:
            items.append({"type": "message", "role": "assistant",
                          "content": [{"type": "output_text", "text": "progress " * 40}]})
        else:
            items.append({"type": "reasoning", "summary": [{"type": "summary_text", "text": "plan " * 10}]})
    return items


def host():
    receipts = {}

    def commit(package):
        receipt = HostReceipt(operation_id=package["operation_id"],
                              package_digest=package["package_digest"],
                              session_id=package["binding"]["session_id"],
                              workspace=package["binding"]["workspace"],
                              generation=package["next_generation"],
                              control_epoch=package["binding"]["control_epoch"],
                              installed_through=package["through"],
                              receiver="benchmark-host", evidence_accessible=True)
        receipts[package["operation_id"]] = receipt
        return receipt

    def lookup(operation_id):
        return receipts.get(operation_id)

    return CallbackHost(commit=commit, lookup=lookup)


def run(count, *, archive=False, profile=False, batch_present=False, sync=True):
    adapter = CodexCheckpointAdapter()
    items = make_items(count)
    events = adapter.import_items(items, thread_id="benchmark")
    timings = {}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Store(root / "state.db", session_id="bench", workspace=str(root))
        try:
            core = WSC(store, access=lambda *_: True, evidence_sync=sync)
        except TypeError:
            core = WSC(store, access=lambda *_: True)
        batch = 200
        start = time.perf_counter()
        for offset in range(0, len(events), batch):
            core.ingest(events[offset:offset + batch])
        timings["ingest"] = time.perf_counter() - start

        receipts = [(f"present:{event.call_id}", (event.id,), "benchmark-host")
                    for event in events if event.kind == "result"]
        start = time.perf_counter()
        if batch_present and hasattr(core, "presented_many"):
            core.presented_many(receipts)
        else:
            for request_id, source_ids, receiver in receipts:
                core.presented(request_id, source_ids, receiver=receiver)
        timings["present"] = time.perf_counter() - start

        start = time.perf_counter()
        snapshot = core.capture()
        timings["capture"] = time.perf_counter() - start

        start = time.perf_counter()
        material = core.material(snapshot)
        timings["material"] = time.perf_counter() - start

        selectable = tuple(row["id"] for row in snapshot.events if row["kind"] != "opaque")
        start = time.perf_counter()
        view = core.prepare(snapshot, Selection(source_ids=selectable), producer="benchmark",
                            limits=Limits(max_view_bytes=8_000_000, max_material_bytes=32_000_000))
        timings["prepare"] = time.perf_counter() - start

        start = time.perf_counter()
        operation = core.stage(view, directory=root / "out", adapter=adapter,
                               archive_directory=root / "cold" if archive else None)
        timings["stage"] = time.perf_counter() - start

        start = time.perf_counter()
        core.install(operation, host())
        timings["install"] = time.perf_counter() - start

        timings["_events"] = len(snapshot.events)
        timings["_material_bytes"] = len(json.dumps(material, ensure_ascii=False).encode())
        timings["_view_bytes"] = len(json.dumps(core.store and view).encode())

    if profile:
        return timings, None
    return timings, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=1200)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--batch-present", action="store_true")
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    if args.profile:
        profiler = cProfile.Profile()
        profiler.enable()
        run(args.events)
        profiler.disable()
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(28)
        return 0

    samples = []
    for _ in range(args.rounds):
        timings, _ = run(args.events, archive=args.archive, batch_present=args.batch_present,
                         sync=not args.no_sync)
        samples.append(timings)
    keys = [key for key in samples[0] if not key.startswith("_")]
    result = {"format": "wsc.pipeline_timing/1", "events": args.events, "rounds": args.rounds,
              "archive": args.archive, "batch_present": args.batch_present, "sync": not args.no_sync,
              "phases": {key: round(statistics.median([s[key] for s in samples]), 4) for key in keys},
              "info": {key: samples[0][key] for key in samples[0] if key.startswith("_")}}
    result["total"] = round(sum(result["phases"].values()), 4)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
