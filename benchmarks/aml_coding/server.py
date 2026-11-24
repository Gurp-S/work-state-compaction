"""AML Coding Track Add/Search service over CSM.

Add stores evidence and one memory binding per item; Search returns ranked evidence only.
The platform owns answer generation, scoring and review, so this service never calls a model.

    python benchmarks/aml_coding/server.py --host 127.0.0.1 --port 8099

AML_API_KEY enables bearer / X-API-Key authentication. One SQLite file is kept per run id
(header X-AML-Run, or run_id / namespace / task_id in the body), so samples never share
state, as the coding track requires.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import sys
import threading
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks" / "aml_coding"))

import protocol  # noqa: E402
from wsc.contracts import WSCError  # noqa: E402
from wsc.csm import CSM, CSMError, CsmStore, Event, MemoryCandidate  # noqa: E402

MAX_BODY = 64 * 1024 * 1024
_SERVICES: dict[tuple[str, str], CSM] = {}
_LOCK = threading.Lock()
_DB_ROOT = ROOT / ".bench" / "aml-coding"
_API_KEY = ""


def safe_run_id(value) -> str:
    text = str(value or "").strip() or "default"
    return (re.sub(r"[^A-Za-z0-9._-]", "_", text)[:64] or "default")


def service(run_id: str) -> CSM:
    key = (str(_DB_ROOT), run_id)
    with _LOCK:
        if key not in _SERVICES:
            _DB_ROOT.mkdir(parents=True, exist_ok=True)
            _SERVICES[key] = CSM(CsmStore(_DB_ROOT / f"aml-{run_id}.db",
                                          namespace=f"aml:{run_id}"))
        return _SERVICES[key]


def add(store: CSM, body: dict) -> dict:
    defaults = {"default_scope": body.get("scope") or body.get("repo"),
                "default_commit": body.get("commit")}
    raw_items = body.get("items")
    if raw_items is None:
        raw_items = [body] if any(key in body for key in ("content", "text")) else []
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("items_missing")
    acked = []
    for raw in raw_items:
        try:
            record = protocol.item(raw, **defaults)
            ingested = store.ingest([Event(
                id=record["id"], source_type=record["source_type"],
                payload={"text": record["content"]}, source_ref=record["source_ref"],
                observed_at=record["observed_at"], metadata=record["metadata"])])
            written = store.remember([MemoryCandidate(
                entity=record["entity"], slot=record["slot"], value=record["value"],
                semantic_type=record["semantic_type"],
                property_kind=record["property_kind"], scope=record["scope"],
                topics=tuple(record["topics"]), symbols=tuple(record["symbols"]),
                source_ids=(record["id"],))],
                producer="aml-add")[0]
            acked.append({"id": record["id"],
                          "status": "existing" if record["id"] in ingested["existing"]
                          else "stored",
                          "memory_id": written["memory_id"],
                          "property_kind": written.get("property_kind"),
                          "scope": written.get("scope"),
                          **({"commit": written["commit"]} if written.get("commit") else {})})
        except (CSMError, WSCError, ValueError, TypeError) as error:
            acked.append({"id": raw.get("id") if isinstance(raw, dict) else None,
                          "status": "error", "error": str(error)})
    return {"added": acked, "count": len(acked),
            "errors": sum(1 for item in acked if item["status"] == "error")}


def search(store: CSM, body: dict) -> dict:
    request = protocol.search_request(body)
    window = (None, request["as_of"]) if request["as_of"] and not request["at_commit"] else None
    packet = store.search(request["query"], limit=request["top_k"], window=window,
                          scope=request["scope"], scope_chain=request["scope_chain"],
                          at_commit=request["at_commit"], anchor=request["anchor"],
                          anchor_terms=request["anchor_terms"])
    mapped, used, truncated = [], 0, 0
    for rank, row in enumerate(packet["results"]):
        item = protocol.result_row(row, rank)
        size = len(item["content"]) + len(json.dumps(item["metadata"], ensure_ascii=False))
        if mapped and used + size > protocol.MAX_SEARCH_CHARS:
            truncated = len(packet["results"]) - len(mapped)
            break
        mapped.append(item)
        used += size
    return {"results": mapped, "count": len(mapped), "top_k": request["top_k"],
            "scope": request["scope"], "scope_chain": request["scope_chain"],
            "at_commit": request["at_commit"], "as_of": request["as_of"],
            "truncated": truncated}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "csm-aml/0.1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not _API_KEY:
            return True
        presented = self.headers.get("X-API-Key", "")
        bearer = self.headers.get("Authorization", "")
        if bearer.lower().startswith("bearer "):
            presented = bearer[7:].strip()
        return hmac.compare_digest(presented, _API_KEY)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] not in ("/health", "/v1/health"):
            self._json(404, {"error": "not_found"})
            return
        self._json(200, {"status": "ok", "service": "csm-aml",
                         "contract": "cambench-coding-relevant-noisy-300-v1",
                         "protocol": "add/search (provisional field mapping)",
                         "db_root": str(_DB_ROOT)})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path not in ("/add", "/v1/add", "/search", "/v1/search"):
            self._json(404, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise ValueError("body_invalid")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("body_invalid")
            run = safe_run_id(self.headers.get("X-AML-Run") or body.get("run_id")
                              or body.get("namespace") or body.get("task_id"))
            store = service(run)
            self._json(200, add(store, body) if path.endswith("/add")
                       else search(store, body))
        except (CSMError, WSCError, ValueError, TypeError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:  # one bad request must not kill the service
            traceback.print_exc()
            self._json(500, {"error": type(error).__name__})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def build_server(host: str = "127.0.0.1", port: int = 8099, *,
                 db_root: str | Path | None = None, api_key: str | None = None
                 ) -> ThreadingHTTPServer:
    global _DB_ROOT, _API_KEY
    if db_root is not None:
        _DB_ROOT = Path(db_root).resolve()
    _API_KEY = api_key if api_key is not None else os.environ.get("AML_API_KEY", "")
    if host not in ("127.0.0.1", "localhost", "::1") and not _API_KEY:
        raise SystemExit("api_key_required: set AML_API_KEY before binding a public interface")
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--db-root", default=str(ROOT / ".bench" / "aml-coding"))
    args = parser.parse_args()
    server = build_server(args.host, args.port, db_root=args.db_root)
    print(json.dumps({"listening": f"http://{args.host}:{server.server_port}",
                      "db_root": str(Path(args.db_root).resolve()),
                      "auth": bool(_API_KEY)}, ensure_ascii=False), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
