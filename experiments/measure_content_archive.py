"""Offline storage/latency comparison; no model, semantic ranking or host receipt."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsc import WSC, Store, Event, Selection
from wsc.adapters.codex import CodexCheckpointAdapter


def measure():
    cases = {}
    with tempfile.TemporaryDirectory(prefix="wsc-export-comparison-") as temporary:
        root = Path(temporary)
        for label, shared in (("standalone", False), ("shared", True)):
            area = root / label
            core = WSC(Store(area / "state.db", session_id="export-benchmark", workspace=str(area)),
                       access=lambda *args: True)
            batch = [Event(id=f"source-{i}", kind="observation",
                           payload={"text": f"{i} " + "evidence text " * 630},
                           text=f"{i} " + "evidence text " * 630, observed_at="2026-10-22T00:00:00Z")
                     for i in range(256)]
            core.ingest(batch)
            view = core.prepare(core.capture(), Selection(), producer="offline-mechanical-benchmark")
            runs = []
            for _ in range(3):
                began = time.perf_counter()
                op = core.stage(view, directory=area / "exports", adapter=CodexCheckpointAdapter(),
                                archive_directory=area / "cold" if shared else None)
                elapsed = time.perf_counter() - began
                package = core.package(op)
                files = [p for directory in (area / "exports", area / "cold")
                         for p in directory.rglob("*") if p.is_file()]
                runs.append({"stage_seconds": elapsed, "evidence_count": len(package["evidence"]),
                             "total_files": len(files), "total_bytes": sum(p.stat().st_size for p in files)})
                core.discard(op)
            cases[label] = runs
    source = Path(__file__).resolve().parents[1]
    return {"scope": "synthetic same-source three-stage storage comparison; no model or installation",
            "events": 256, "text_bytes": sum(len(e.text.encode()) for e in batch), "cases": cases,
            "source_sha256": {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest()
                              for directory in (source / "src", source / "experiments")
                              for p in sorted(directory.rglob("*.py"))}}


if __name__ == "__main__":
    value = measure()
    with Path(sys.argv[1]).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in value.items() if k != "source_sha256"}, indent=2))
