# -*- coding: utf-8 -*-
"""Bench 2.2 metering gateway.

Every model call a memory system makes (chat, embedding, rerank) must go through this
gateway (point OPENAI_BASE_URL at it).  The gateway holds the provider keys, so a system
cannot reach a provider directly with our keys, and it prices every call with prices.json:

    cost = tokens x fixed price, whatever the provider really billed and whether or not
    the response came from the replay cache.

Local models: serve them behind an OpenAI-compatible endpoint, set BENCH22_LOCAL_URL on the gateway and call them as
"local:<name>"; the gateway forwards, counts the tokens the server reports and prices them as deepseek-v4.1-flash.

Routes (OpenAI-like):
    POST /v1/chat/completions   body: OpenAI chat body.  model deepseek-* -> DeepSeek, qwen* -> Bailian
    POST /v1/embeddings         body: {model, input:[...], dimensions, text_type, instruct}
    POST /v1/rerank             body: {model, query, documents, top_n, instruct}
    GET  /v1/usage              totals so far (per phase)

Request headers used for accounting: X-Bench-Run, X-Bench-System, X-Bench-Phase, X-Bench-Tag.
Phases: ingest | retrieve | answer | judge | gen | review.
Keys are read here only and never written to any file or log.
Run cost ceiling: every metered call of a run (the system's own calls AND the evaluator's answering/judging) counts toward the run's
total at the published price list; once the total reaches `run_cost_ceiling_cny` (score_config.json, default 50 = the deposit) the gateway
answers 403 RUN_COST_CEILING, the runner stops that run with no score, and the deposit is kept, nothing more is owed.
Run:  python -m bench22.gateway --port 18877 --cap-usd 9.5
"""
import argparse
import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OPENCODE_KEY_FILE = os.environ.get("BENCH22_DEEPSEEK_KEY_FILE", "")
DEEPSEEK_URL = "https://opencode.ai/zen/go/v1/chat/completions"
DASH_COMPAT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DASH_NATIVE = "https://dashscope.aliyuncs.com/api/v1/services/"
DEFAULT_INSTRUCT = "Retrieve past conversation turns needed to respond to the current user message accurately."

PRICES = json.load(open(os.path.join(HERE, "prices.json"), encoding="utf-8"))
USD_CNY = PRICES["usd_cny"]


def price_cny(model, tin, tout):
    p = PRICES["models"][model]
    return (tin * p["in_per_mtok"] + tout * p.get("out_per_mtok", 0)) / 1e6


class Ledger:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.lock = threading.Lock()
        self.real_cny = 0.0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    self.real_cny += r.get("real_cny", 0.0)

    def add(self, rec):
        with self.lock:
            self.real_cny += rec.get("real_cny", 0.0)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @property
    def real_usd(self):
        return self.real_cny / USD_CNY


class Cache:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=60)
        self.db.execute("pragma journal_mode=wal")
        self.db.execute("pragma synchronous=off")          # the cache only saves money; losing a few rows in a crash costs a re-call
        self.db.execute("create table if not exists c (k text primary key, v text not null)")
        self.lock = threading.Lock()

    def get(self, k):
        with self.lock:
            r = self.db.execute("select v from c where k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else None

    def put(self, k, v):
        with self.lock:
            self.db.execute("insert or replace into c values (?,?)", (k, json.dumps(v, ensure_ascii=False)))
            self.db.commit()


class State:
    ledger = None
    cache = None
    cap_usd = 9.5
    keys = {}
    eval_token = os.environ.get("BENCH22_EVAL_TOKEN", "")      # held only by the evaluator process; entries never get it
    run_ceiling_cny = 50.0
    entry_cost = None                                      # (run, system) -> metered CNY of ALL calls of the run (the system's own + answering + judging)
    entry_lock = threading.Lock()
    sem = {"deepseek": threading.Semaphore(int(os.environ.get("BENCH22_DEEPSEEK_CONCURRENCY", "4"))), "dash": threading.Semaphore(int(os.environ.get("BENCH22_DASH_CONCURRENCY", "6")))}


def _key(provider):
    if provider in State.keys:
        return State.keys[provider]
    if provider == "deepseek":
        with open(OPENCODE_KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
    else:
        k = os.environ["DASHSCOPE_API_KEY"]
    State.keys[provider] = k
    return k


def _post(url, body, provider, extra_headers=None, timeout=300, retries=6):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": "Bearer " + _key(provider), "Content-Type": "application/json",
               "User-Agent": "memory-bench-gateway/2.2"}
    headers.update(extra_headers or {})
    last = None
    for attempt in range(retries):
        try:
            with State.sem[provider]:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {msg}"
            if e.code in (408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529):
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as e:
            last = f"net {type(e).__name__}: {str(e)[:150]}"
            time.sleep(min(60, 2 ** attempt * 2))
    raise RuntimeError("upstream failed: " + str(last))


UPSTREAM = os.environ.get("BENCH22_BAILIAN_UPSTREAM", "").rstrip("/")   # e.g. http://127.0.0.1:18877 : forward Bailian calls to another gateway that holds the key
LOCAL_URL = os.environ.get("BENCH22_LOCAL_URL", "")        # OpenAI-compatible server for local models, e.g. http://127.0.0.1:8000/v1
PRICE_AS = "deepseek-v4.1-flash"                           # local models are priced as flash


def _priced(model):
    """Price-table key for a model name; local:* models are priced as deepseek-v4.1-flash."""
    return PRICE_AS if model.startswith("local:") else model


def _local_post(path, body):
    if not LOCAL_URL:
        raise RuntimeError("BENCH22_LOCAL_URL is not set on the gateway")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(LOCAL_URL.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _upstream_post(path, body, meta):
    """Forward a Bailian call to the gateway that holds the Bailian key (BENCH22_BAILIAN_UPSTREAM); same accounting headers."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    hdr = {"Content-Type": "application/json", "Authorization": "Bearer evaluator-gateway",
           "X-Bench-Run": meta["run"], "X-Bench-System": meta["system"], "X-Bench-Phase": meta["phase"], "X-Bench-Tag": meta["tag"]}
    last = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(UPSTREAM + path, data=data, headers=hdr, method="POST")
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            if e.code in (400, 402, 404):
                raise RuntimeError(last)
        except Exception as e:  # noqa
            last = f"{type(e).__name__}: {str(e)[:120]}"
        time.sleep(min(20, 2 ** attempt))
    raise RuntimeError("upstream failed: " + str(last))


def _provider_for_chat(model):
    if model.startswith("local:"):
        return "local"
    return "deepseek" if model.startswith("deepseek") else "dash"


SYSTEM_PHASES = ("ingest", "retrieve")


def _load_ceiling():
    cp = os.path.join(HERE, "score_config.json")
    if os.path.exists(cp):
        State.run_ceiling_cny = float(json.load(open(cp, encoding="utf-8")).get("run_cost_ceiling_cny", 50.0))


_load_ceiling()


def is_entry_call(meta, token):
    """A call belongs to the entry (counts toward its cost ceiling) unless it carries the evaluator token.
    Without a configured token (development), the phase header decides."""
    if State.eval_token:
        return token != State.eval_token
    return meta.get("phase") in SYSTEM_PHASES


def entry_key(meta):
    return (meta.get("run", ""), (meta.get("system", "") or "").split(":")[0])


def _load_entry_cost():
    State.entry_cost = {}
    path = State.ledger.path if State.ledger else None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                k = (r.get("run", ""), (r.get("system", "") or "").split(":")[0])
                State.entry_cost[k] = State.entry_cost.get(k, 0.0) + r.get("cost_cny", 0.0)


def ceiling_exceeded(meta, token):
    """True when this run (system + answering + judging, all metered) has already reached the ceiling: every further call of the run is refused."""
    with State.entry_lock:
        if State.entry_cost is None:
            _load_entry_cost()
        return State.entry_cost.get(entry_key(meta), 0.0) >= State.run_ceiling_cny


def add_entry_cost(meta, token, cost):
    with State.entry_lock:
        if State.entry_cost is None:
            _load_entry_cost()
        k = entry_key(meta)
        State.entry_cost[k] = State.entry_cost.get(k, 0.0) + cost


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/v1/usage"):
            tot = {}
            with open(State.ledger.path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    k = r.get("phase", "?")
                    t = tot.setdefault(k, {"calls": 0, "cny": 0.0, "real_cny": 0.0})
                    t["calls"] += 1
                    t["cny"] += r["cost_cny"]
                    t["real_cny"] += r["real_cny"]
            return self._send(200, {"real_usd_total": State.ledger.real_usd, "cap_usd": State.cap_usd, "phases": tot})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return self._send(400, {"error": "bad json"})
        meta = {"run": self.headers.get("X-Bench-Run", ""), "system": self.headers.get("X-Bench-System", ""),
                "phase": self.headers.get("X-Bench-Phase", "unknown"), "tag": self.headers.get("X-Bench-Tag", "")}
        token = self.headers.get("X-Bench-Eval-Token", "")
        self._token = token
        if ceiling_exceeded(meta, token):
            return self._send(403, {"error": "run cost ceiling reached (%s CNY in total): the run stops and gets no score (deposit kept, nothing more owed)" % State.run_ceiling_cny, "code": "RUN_COST_CEILING"})
        if State.ledger.real_usd >= State.cap_usd:
            return self._send(402, {"error": f"spend cap reached ({State.ledger.real_usd:.2f} >= {State.cap_usd} USD)"})
        try:
            if self.path == "/v1/chat/completions":
                out = self.chat(body, meta)
            elif self.path == "/v1/embeddings":
                out = self.embed(body, meta)
            elif self.path == "/v1/rerank":
                out = self.rerank(body, meta)
            elif self.path == "/v1/charge":
                out = self.charge(body, meta)
            else:
                return self._send(404, {"error": "unknown route"})
        except KeyError as e:
            return self._send(400, {"error": f"unknown model or field {e}"})
        except Exception as e:  # noqa
            return self._send(502, {"error": str(e)[:400]})
        self._send(200, out)

    # ---- metered calls -------------------------------------------------
    def _cached(self, route, body, call):
        k = hashlib.sha256((route + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()
        hit = State.cache.get(k)
        if hit is not None:
            return hit, True, 0.0
        t0 = time.time()
        resp = call()
        State.cache.put(k, resp)
        return resp, False, time.time() - t0

    def _record(self, meta, route, model, tin, tout, cached, secs):
        cost = price_cny(model, tin, tout)      # model is already a price-table key
        ent = is_entry_call(meta, getattr(self, "_token", ""))
        add_entry_cost(meta, getattr(self, "_token", ""), cost)
        State.ledger.add({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **meta, "entry": ent, "route": route, "model": model,
                          "in_tokens": tin, "out_tokens": tout, "cost_cny": round(cost, 8),
                          "real_cny": 0.0 if cached else round(cost, 8), "cached": cached, "seconds": round(secs, 3)})
        return cost

    def charge(self, body, meta):
        """Replay charge: books tokens that a previous REAL call of the same system consumed (used only when the
        provider is unreachable and retrieval is replayed from recorded results).  Priced exactly like a live call;
        never costs real money (real_cny = 0) and is marked replay=true in the ledger."""
        model = body["model"]
        PRICES["models"][model]
        cost = price_cny(model, body.get("in_tokens", 0), body.get("out_tokens", 0))
        ent = is_entry_call(meta, getattr(self, "_token", ""))
        add_entry_cost(meta, getattr(self, "_token", ""), cost)
        State.ledger.add({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **meta, "entry": ent, "route": body.get("route", "replay"), "model": model,
                          "in_tokens": body.get("in_tokens", 0), "out_tokens": body.get("out_tokens", 0), "cost_cny": round(cost, 8),
                          "real_cny": 0.0, "cached": True, "replay": True, "seconds": 0})
        return {"ok": True, "cost_cny": cost}

    def chat(self, body, meta):
        model = body["model"]
        prov = _provider_for_chat(model)
        PRICES["models"][_priced(model)]
        b = dict(body)
        if prov == "local":
            lb = dict(b, model=model[len("local:"):])
            resp, cached, secs = self._cached("chat", b, lambda: _local_post("/chat/completions", lb))
            u = resp.get("usage") or {}
            self._record(meta, "chat", _priced(model), u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cached, secs)
            return resp
        if prov == "dash" and UPSTREAM:
            resp, cached, secs = self._cached("chat", b, lambda: _upstream_post("/v1/chat/completions", b, meta))
            u = resp.get("usage") or {}
            self._record(meta, "chat", model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cached, 0.0)
            return resp
        if prov == "dash":
            b.setdefault("enable_thinking", False)
        url = DEEPSEEK_URL if prov == "deepseek" else DASH_COMPAT
        hdr = {"x-opencode-session": meta["run"] or "bench22"} if prov == "deepseek" else None
        resp, cached, secs = self._cached("chat", b, lambda: _post(url, b, prov, hdr))
        u = resp.get("usage") or {}
        self._record(meta, "chat", model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cached, secs)
        return resp

    def embed(self, body, meta):
        model = body["model"]
        if model.startswith("local:"):
            lb = dict(body, model=model[len("local:"):])
            resp, cached, secs = self._cached("embed", body, lambda: _local_post("/embeddings", lb))
            u = resp.get("usage") or {}
            self._record(meta, "embed", _priced(model), u.get("prompt_tokens", u.get("total_tokens", 0)), 0, cached, secs)
            return resp
        PRICES["models"][model]
        if UPSTREAM:
            resp, cached, secs = self._cached("embed", body, lambda: _upstream_post("/v1/embeddings", body, meta))
            tok = (resp.get("usage") or {}).get("total_tokens", 0)
            self._record(meta, "embed", model, tok, 0, cached, 0.0)
            return resp
        texts = body["input"]
        is_q = body.get("text_type") == "query"
        params = {"dimension": body.get("dimensions", 2560), "text_type": "query" if is_q else "document"}
        if is_q:
            params["instruct"] = body.get("instruct", DEFAULT_INSTRUCT)
        nb = {"model": model, "input": {"texts": texts}, "parameters": params}
        url = DASH_NATIVE + "embeddings/text-embedding/text-embedding"
        resp, cached, secs = self._cached("embed", nb, lambda: _post(url, nb, "dash"))
        tok = (resp.get("usage") or {}).get("total_tokens", 0)
        self._record(meta, "embed", model, tok, 0, cached, secs)
        rows = sorted(resp["output"]["embeddings"], key=lambda x: x["text_index"])
        return {"object": "list", "model": model, "usage": {"total_tokens": tok, "prompt_tokens": tok},
                "data": [{"index": r["text_index"], "embedding": r["embedding"]} for r in rows]}

    def rerank(self, body, meta):
        model = body["model"]
        if model.startswith("local:"):
            lb = dict(body, model=model[len("local:"):])
            resp, cached, secs = self._cached("rerank", body, lambda: _local_post("/rerank", lb))
            u = resp.get("usage") or {}
            self._record(meta, "rerank", _priced(model), u.get("prompt_tokens", u.get("total_tokens", 0)), 0, cached, secs)
            return resp
        PRICES["models"][model]
        if UPSTREAM:
            resp, cached, secs = self._cached("rerank", body, lambda: _upstream_post("/v1/rerank", body, meta))
            tok = (resp.get("usage") or {}).get("total_tokens", 0)
            self._record(meta, "rerank", model, tok, 0, cached, 0.0)
            return resp
        nb = {"model": model, "input": {"query": body["query"], "documents": body["documents"]},
              "parameters": {"top_n": body.get("top_n", len(body["documents"])), "return_documents": False,
                             "instruct": body.get("instruct", DEFAULT_INSTRUCT)}}
        url = DASH_NATIVE + "rerank/text-rerank/text-rerank"
        resp, cached, secs = self._cached("rerank", nb, lambda: _post(url, nb, "dash"))
        tok = (resp.get("usage") or {}).get("total_tokens", 0)
        self._record(meta, "rerank", model, tok, 0, cached, secs)
        return {"model": model, "usage": {"total_tokens": tok, "prompt_tokens": tok},
                "results": [{"index": r["index"], "relevance_score": r["relevance_score"]} for r in resp["output"]["results"]]}


def serve(port, ledger_path, cache_path, cap_usd):
    State.ledger = Ledger(ledger_path)
    State.cache = Cache(cache_path)
    State.cap_usd = cap_usd
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    print(f"gateway on 127.0.0.1:{port}  prices={PRICES['version']}  spent_so_far_usd={State.ledger.real_usd:.3f} cap={cap_usd}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18877)
    ap.add_argument("--ledger", default=os.path.join(ROOT, "runs", "bench22", "spend-ledger.jsonl"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "runs", "bench22", "gateway-cache.sqlite3"))
    ap.add_argument("--cap-usd", type=float, default=9.5)
    ap.add_argument("--run-ceiling-cny", type=float, default=None, help="override score_config run_cost_ceiling_cny")
    a = ap.parse_args()
    if a.run_ceiling_cny is not None:
        State.run_ceiling_cny = a.run_ceiling_cny
    serve(a.port, a.ledger, a.cache, a.cap_usd)
