"""A/B the two evidence writers on identical payload sets; no model calls.

Compares evidence.write_once (direct create) with ResourceIO.write_once
(temp file plus link, descriptor checks) on the same bytes, then reports
wall time and peak allocation for first writes and for conflict re-writes.
"""
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from wsc.evidence import write_once as direct_write
from wsc.resource_io import ResourceIO


SIZES = (1024, 16384, 262144)
COUNT = 60
ROUNDS = 5


def payloads():
    return [(f"object-{index}-{size}.json", bytes([index % 251]) * size)
            for size in SIZES for index in range(COUNT)]


def measure(writer, root, items, existing):
    tracemalloc.start()
    start = time.perf_counter()
    for name, payload in items:
        writer(root / name, payload)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak


def run(writer, items):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = measure(writer, root, items, False)
        conflict = measure(writer, root, items, True)
        for name, payload in items:
            if (root / name).read_bytes() != payload:
                raise SystemExit(f"content mismatch: {name}")
        return {"first_write_seconds": first[0], "first_peak_bytes": first[1],
                "conflict_write_seconds": conflict[0], "conflict_peak_bytes": conflict[1]}


def summarise(label, samples):
    def pick(key):
        values = [s[key] for s in samples]
        return {"median": round(statistics.median(values), 4),
                "min": round(min(values), 4), "max": round(max(values), 4)}
    return {label: {key: pick(key) for key in samples[0]}}


def main():
    items = payloads()
    io = ResourceIO()
    arms = {"direct": direct_write, "resource_io": io.write_once}
    samples = {name: [] for name in arms}
    for _ in range(ROUNDS):
        for name, writer in arms.items():
            samples[name].append(run(writer, items))
    result = {"format": "wsc.write_path_ab/1", "objects": len(items),
              "bytes_total": sum(len(p) for _, p in items), "rounds": ROUNDS,
              "arms": {}}
    for name in arms:
        result["arms"].update(summarise(name, samples[name]))
    direct = result["arms"]["direct"]
    resource = result["arms"]["resource_io"]
    result["ratio"] = {
        key: round(resource[key]["median"] / direct[key]["median"], 3)
        for key in ("first_write_seconds", "conflict_write_seconds")
    }
    result["ratio"]["first_peak_bytes"] = round(
        resource["first_peak_bytes"]["median"] / max(1, direct["first_peak_bytes"]["median"]), 3)
    result["ratio"]["conflict_peak_bytes"] = round(
        resource["conflict_peak_bytes"]["median"] / max(1, direct["conflict_peak_bytes"]["median"]), 3)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
