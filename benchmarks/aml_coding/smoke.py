"""End-to-end Add/Search smoke test over HTTP against a fresh CSM store.

    python benchmarks/aml_coding/smoke.py

Covers: idempotent Add, branch-over-repository state, exact scope, commit as-of, top_k clamp,
run isolation, credential scrubbing and bearer authentication.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks" / "aml_coding"))

from server import build_server  # noqa: E402

A = "a" * 40
B = "b" * 40
KEY = "smoke-key"
RUN = "smoke-run"

ITEMS = [
    {"id": "m1", "content": "Run make build for a full build", "entity": "acme/api",
     "slot": "build_command", "value": "make build", "property_kind": "state",
     "scope": "acme/api", "observed_at": "2026-01-01T00:00:00Z", "commit": A},
    {"id": "m2", "content": "Run make build-fast on main", "entity": "acme/api",
     "slot": "build_command", "value": "make build-fast", "property_kind": "state",
     "repo": "acme/api", "branch": "main", "observed_at": "2026-02-01T00:00:00Z",
     "commit": B},
    {"id": "m3", "content": "Decision: use postgres for primary storage", "entity": "acme/api",
     "slot": "decision", "scope": "acme/api", "observed_at": "2026-01-01T00:00:00Z",
     "commit": A},
    {"id": "m4", "content": "Decision: use sqlite for the edge cache", "entity": "acme/api",
     "slot": "decision", "scope": "acme/api", "observed_at": "2026-02-01T00:00:00Z",
     "commit": B},
    {"id": "m5", "content": "The weather was sunny during the release", "entity": "acme/api",
     "slot": "observation", "scope": "acme/api", "observed_at": "2026-01-01T00:00:00Z",
     "commit": A},
    {"id": "m6", "content": "Deploy password=hunter2secret for staging",
     "entity": "acme/api", "slot": "deploy_note", "scope": "acme/api",
     "observed_at": "2026-01-01T00:00:00Z", "commit": A},
    {"id": "m7", "content": "CI uses docker compose", "entity": "acme/api", "slot": "ci",
     "scope": "acme/api", "observed_at": "2026-01-01T00:00:00Z", "commit": A},
]

FAILS: list[str] = []


def check(name: str, condition: bool, detail=None) -> None:
    print(("PASS " if condition else "FAIL ") + name +
          ("" if condition or detail is None else f" :: {detail}"), flush=True)
    if not condition:
        FAILS.append(name)


def main() -> int:
    directory = tempfile.TemporaryDirectory()
    server = build_server("127.0.0.1", 0, db_root=Path(directory.name), api_key=KEY)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path: str, body=None, *, run: str | None = RUN, key: str | None = KEY):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(base + path, data=data, method="POST" if body else "GET")
        request.add_header("Content-Type", "application/json")
        if run:
            request.add_header("X-AML-Run", run)
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    try:
        status, health = call("/health", None, run=None, key=None)
        check("health", status == 200 and health.get("status") == "ok", health)

        status, first = call("/add", {"items": ITEMS})
        check("add all", status == 200 and first.get("count") == 7 and first.get("errors") == 0,
              first)
        check("add records commit", any(row.get("commit") == A for row in first.get("added", [])),
              first)

        status, second = call("/add", {"items": ITEMS})
        check("add idempotent",
              status == 200 and all(row["status"] == "existing" for row in second["added"]),
              second)

        status, branch = call("/search", {"query": "build command", "repo": "acme/api",
                                         "branch": "main"})
        results = branch.get("results") or []
        check("branch overrides repository",
              status == 200 and len(results) == 1
              and "build-fast" in results[0]["content"], branch)

        status, exact = call("/search", {"query": "build command", "repo": "acme/api",
                                        "scope_exact": True})
        results = exact.get("results") or []
        check("exact scope hides branch",
              status == 200 and len(results) == 1 and "build-fast" not in results[0]["content"]
              and "make build" in results[0]["content"], exact)

        status, old = call("/search", {"query": "sqlite", "at_commit": A})
        check("commit as-of excludes later decision", status == 200 and old.get("count") == 0, old)
        status, new = call("/search", {"query": "sqlite", "at_commit": B})
        check("commit as-of includes later decision", status == 200 and new.get("count") == 1, new)

        status, state_old = call("/search", {"query": "make build", "at_commit": A,
                                            "repo": "acme/api", "branch": "main"})
        check("state search at commit",
              status == 200 and state_old.get("count") == 1
              and "make build" in state_old["results"][0]["content"], state_old)

        status, top = call("/search", {"query": "command", "top_k": 5000})
        check("top_k clamped", status == 200 and top.get("top_k") == 1000, top)

        status, other = call("/search", {"query": "build command"}, run="other-run")
        check("run isolation", status == 200 and other.get("count") == 0, other)

        status, secret = call("/search", {"query": "password"})
        text = json.dumps(secret, ensure_ascii=False)
        check("credential scrubbed",
              status == 200 and secret.get("count") == 1
              and "hunter2secret" not in text and "[REDACTED" in text, secret)

        status, denied = call("/add", {"items": ITEMS[:1]}, key=None)
        check("missing key rejected", status == 401, denied)
        status, denied = call("/add", {"items": ITEMS[:1]}, key="wrong")
        check("wrong key rejected", status == 401, denied)
    finally:
        server.shutdown()
        server.server_close()
        directory.cleanup()

    print(json.dumps({"checks": 14, "failed": FAILS}, ensure_ascii=False))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
