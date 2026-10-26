"""Offline preparation cost only; no model calls or source-validation shortcuts."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc


def measure(callback, repeats=3):
    elapsed = []
    values = []
    for _ in range(repeats):
        began = time.perf_counter()
        values.append(callback())
        elapsed.append(time.perf_counter() - began)
    tracemalloc.start()
    callback()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"seconds": elapsed, "median_seconds": statistics.median(elapsed),
            "peak_python_bytes": peak}, values


def run(source_root, output):
    sys.path.insert(0, str(source_root / "src"))
    from wsc import WSC, Store, Event, Selection, Understanding, Limits
    from wsc.contracts import digest
    from wsc.projection import snapshot_binding, public_material

    def legacy_material(prefix, records):
        return {"events": [{k: row[k] for k in
                            ("id", "seq", "kind", "role", "call_id", "text", "observed_at")}
                           for row in prefix if row["kind"] != "opaque"],
                "understandings": [r for r in records if set(r["sources"]) <= {s["id"] for s in prefix}]}

    def legacy_binding(snapshot, epoch):
        result = asdict(snapshot)
        result.pop("events")
        result.pop("understandings")
        result["understanding_epoch"] = epoch
        return result

    with tempfile.TemporaryDirectory(prefix="wsc-projection-measure-") as temporary:
        root = Path(temporary)
        core = WSC(Store(root / "state.db", session_id="measurement", workspace=str(root)), access=lambda *args: True)
        observations = [Event("goal", "message", {"text": "Current task"}, role="user", text="Current task")]
        observations += [Event(f"source-{i}", "observation", {"result": "x" * 512, "ordinal": i},
                               text="x" * 512, observed_at="2026-10-21T00:00:00Z") for i in range(2048)]
        core.ingest(observations)
        memories = tuple(Understanding(f"Explicit record {i}", "test_observation",
                            sources=(f"source-{i}", f"source-{i+1}")) for i in range(512))
        core.prepare(core.capture(), Selection(new_understandings=memories), producer="offline_fixture",
                     limits=Limits(max_view_bytes=1048576))
        snapshot = core.capture()
        prefix, records = snapshot.events, snapshot.understandings
        projected = public_material(prefix, records)
        expected = legacy_material(prefix, records)
        assert projected == expected
        assert snapshot_binding(snapshot, understanding_epoch=snapshot.understanding_epoch) == legacy_binding(snapshot, snapshot.understanding_epoch)
        micro = {}
        for label, callback in (
            ("legacy_binding", lambda: legacy_binding(snapshot, snapshot.understanding_epoch)),
            ("candidate_binding", lambda: snapshot_binding(snapshot, understanding_epoch=snapshot.understanding_epoch)),
            ("legacy_material", lambda: legacy_material(prefix, records)),
            ("candidate_material", lambda: public_material(prefix, records))):
            micro[label], _ = measure(callback)

        def actual_cycle():
            snap = core.capture()
            material = core.material(snap)
            view = core.prepare(snap, Selection(), producer="offline_fixture")
            return material, view

        cycle, samples = measure(actual_cycle)
        assert all(value["events"] == projected["events"] and value["understandings"] == projected["understandings"]
                   for value, _ in samples)
        result = {"scope": "Synthetic 2049 events / 512 records; capture + material + prepare, no export/model/native cost claim",
                  "events": len(prefix), "understandings": len(records), "model_calls": 0,
                  "public_material_equal": True, "binding_equal": True,
                  "snapshot_public_history_preserved": len(snapshot.events) == len(prefix) and len(snapshot.understandings) == len(records),
                  "micro": micro, "actual_cycle": cycle,
                  "source_sha256": {p.relative_to(source_root).as_posix(): sha256(p.read_bytes()).hexdigest()
                                    for p in sorted((source_root / "src").rglob("*.py"))}}
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("events", "understandings", "micro", "actual_cycle", "public_material_equal", "binding_equal")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.source_root.resolve(), args.output.resolve())
