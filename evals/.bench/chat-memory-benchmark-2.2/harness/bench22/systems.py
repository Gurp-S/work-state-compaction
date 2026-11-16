# -*- coding: utf-8 -*-
"""Reference system adapters for Bench 2.2.

Adapter contract (what every system must implement; the evaluator enforces the protocol):

    class MySystem(System):
        def ingest(self, turn):            # called once per history turn, strictly in order
        def retrieve(self, question, now, cutoff_turn) -> Retrieval

The evaluator feeds a system ONLY turns up to the exam point's cutoff (see runner.py), never
the history file.  retrieve() must be read-only: nothing the exam asks may be written to memory.
A system makes model calls only through gateway_url (env OPENAI_BASE_URL) so they are metered.
Retrieval.prompt is the memory text placed in front of the question (its tokens are billed to
the system at the flash input price); Retrieval.used_turns lists history turns it shows (checked
against the cutoff by the evaluator).
"""
import collections
import datetime
import json
import math
import os
import re
import threading
import time
import urllib.request

import numpy as np

EMBED_MODEL = "qwen3.7-text-embedding"
RERANK_MODEL = "qwen3.7-text-rerank"
POOL, TOP_K, RECENT, RRF_K = 40, 10, 6, 60


class Retrieval:
    def __init__(self, prompt, used_turns, meta=None):
        self.prompt, self.used_turns, self.meta = prompt, list(used_turns), meta or {}


class Gateway:
    """Tiny client for the evaluator gateway.  Reads the base URL from OPENAI_BASE_URL."""

    def __init__(self, base_url=None, run="", system="", timeout=300, evaluator=False):
        self.base = (base_url or os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18877/v1")).rstrip("/")
        self.run, self.system, self.timeout = run, system, timeout
        # only the evaluator's own answer/judge calls carry the token (set in the evaluator's environment, never an entry's)
        self.token = os.environ.get("BENCH22_EVAL_TOKEN", "") if evaluator else ""
        self.lock = threading.Lock()

    def post(self, route, body, phase, tag=""):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdr = {"Content-Type": "application/json", "X-Bench-Run": self.run, "X-Bench-System": self.system,
               "X-Bench-Phase": phase, "X-Bench-Tag": tag, "Authorization": "Bearer evaluator-gateway"}
        if self.token:
            hdr["X-Bench-Eval-Token"] = self.token
        last = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(self.base + route, data=data, headers=hdr, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode('utf-8', 'replace')[:300]
                last = f"HTTP {e.code}: {body_txt}"
                if e.code == 403 and "RUN_COST_CEILING" in body_txt:
                    raise CeilingExceeded(last)
                if e.code in (402, 400, 404):
                    raise RuntimeError(last)
            except Exception as e:  # noqa
                last = f"{type(e).__name__}: {str(e)[:150]}"
            time.sleep(min(30, 2 ** attempt))
        raise RuntimeError("gateway failed: " + str(last))

    def chat(self, model, messages, phase, tag="", **kw):
        body = {"model": model, "messages": messages, **kw}
        return self.post("/chat/completions", body, phase, tag)

    def embed(self, texts, phase, tag="", query=False):
        body = {"model": EMBED_MODEL, "input": texts, "dimensions": 2560}
        if query:
            body["text_type"] = "query"
        r = self.post("/embeddings", body, phase, tag)
        return [d["embedding"] for d in r["data"]]

    def rerank(self, query, docs, phase, tag=""):
        r = self.post("/rerank", {"model": RERANK_MODEL, "query": query, "documents": docs, "top_n": len(docs)}, phase, tag)
        return r["results"]


class CeilingExceeded(RuntimeError):
    """The entry's own model usage reached the cost ceiling of a sealed run: the run stops and gets no score."""


class Unavailable(RuntimeError):
    """The system cannot answer this exam point right now (e.g. its provider is unreachable)."""


class System:
    name = "base"

    def ingest(self, turn):
        raise NotImplementedError

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        raise NotImplementedError

    # Natural-use board: the evaluator feeds a short per-probe "tail" after the cutoff, then asks the system to forget it again.
    def mark(self):
        """Token for the current memory state (default: number of turns ingested)."""
        return len(getattr(self, "turns", []))

    def rewind(self, token):
        """Drop everything ingested after mark()."""
        raise NotImplementedError


# ---------------------------------------------------------------- presentation
SYS_BASE = "你是用户长期聊天的伴侣，下面是你们过去的聊天片段和最近的对话，请根据记忆自然地回答用户这句话。"


def fmt_base(t, now):
    return f"[{t['time']}]\n用户：{t['user']}\n小满：{t['assistant']}"


def render(blocks, recent, now, style="base"):
    parts = [SYS_BASE, "【过去的聊天片段】"] + [fmt_base(t, now) for t in blocks]
    parts += ["【最近的对话】"] + [fmt_base(t, now) for t in recent]
    return "\n\n".join(parts)


# ---------------------------------------------------------------- BM25
RUN_RE = re.compile(r"[一-鿿]+|[A-Za-z0-9]+")


def tokens(text):
    out = []
    for seg in RUN_RE.findall(text.lower()):
        if re.match(r"[一-鿿]", seg):
            out += list(seg)
            out += [seg[k:k + 2] for k in range(len(seg) - 1)]
        else:
            out.append(seg)
    return out


class IncBM25:
    """BM25 built incrementally: it can only ever know the turns that were ingested."""

    def __init__(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.dl, self.post, self.total = [], collections.defaultdict(list), 0
        self.docs = []

    def add(self, text):
        idx = len(self.dl)
        tk = tokens(text)
        self.dl.append(len(tk))
        self.total += len(tk)
        cnt = collections.Counter(tk)
        self.docs.append(cnt)
        for w, c in cnt.items():
            self.post[w].append((idx, c))

    def truncate(self, n):
        """Forget every document with index >= n (used by the natural-use board to drop a probe's tail)."""
        for idx in range(len(self.dl) - 1, n - 1, -1):
            for w in self.docs[idx]:
                self.post[w].pop()
            self.total -= self.dl[idx]
        del self.dl[n:], self.docs[n:]

    def top(self, query, k):
        N = len(self.dl)
        avg = self.total / N
        sc = collections.defaultdict(float)
        for w, _ in collections.Counter(tokens(query)).items():
            pl = self.post.get(w)
            if not pl:
                continue
            df = len(pl)
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for idx, tf in pl:
                sc[idx] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.dl[idx] / avg))
        return [i for i, _ in sorted(sc.items(), key=lambda x: (-x[1], x[0]))[:k]]


def rrf(lists, k=RRF_K):
    sc = collections.defaultdict(float)
    for L in lists:
        for r, i in enumerate(L):
            sc[i] += 1.0 / (k + r + 1)
    return [i for i, _ in sorted(sc.items(), key=lambda x: (-x[1], x[0]))]


def doc_text(t):
    return f"用户：{t['user']}\n小满：{t['assistant']}"


# ---------------------------------------------------------------- Qwen RAG
class QwenRag(System):
    """qwen-base: exchange chunks -> Qwen3.7 embeddings + BM25 (RRF, pool 40) -> Qwen3.7 rerank top 10
    + last 6 turns.
    leaky=True is the POSITIVE CONTROL used by the sentinel test: it is handed future turns on purpose
    (ingest of any turn, including ones past the cutoff) and does no cutoff filtering."""

    def __init__(self, gw, style="base", leaky=False):
        self.gw, self.style, self.leaky = gw, style, leaky
        self.name = "qwen-" + style
        self.turns, self.vecs, self.pending = [], [], []
        self.bm = IncBM25()

    def ingest(self, turn):
        self.turns.append(turn)
        self.bm.add(doc_text(turn))
        self.pending.append(len(self.turns) - 1)

    def rewind(self, token):
        del self.turns[token:]
        del self.vecs[token:]
        self.pending = [i for i in self.pending if i < token]
        self.bm.truncate(token)

    def _flush(self, tag):
        pend, self.pending = self.pending, []
        if not pend:
            return
        self.vecs.extend([None] * (len(self.turns) - len(self.vecs)))
        # canonical batches: complete blocks of 10 turns aligned to multiples of 10 (so every run and every
        # split asks the embedding service the same questions and shares the cache); a block that is not yet
        # complete at the cutoff is embedded as it stands.  Only turns already ingested are ever sent.
        n_now, pset = len(self.turns), set(pend)
        batches = []
        for b in sorted({i // 10 for i in pend}):
            if 10 * b + 10 <= n_now:
                batches.append(list(range(10 * b, 10 * b + 10)))
            else:
                batches.append([i for i in range(10 * b, n_now) if i in pset])
        from concurrent.futures import ThreadPoolExecutor

        def one(b):
            return b, self.gw.embed([doc_text(self.turns[i]) for i in b], "ingest", tag)
        with ThreadPoolExecutor(4) as ex:
            for b, vs in ex.map(one, batches):
                for i, v in zip(b, vs):
                    a = np.asarray(v, dtype=np.float32)
                    self.vecs[i] = a / np.linalg.norm(a)

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        self._flush("flush")
        n = len(self.turns)
        if not self.leaky:
            assert n == cutoff_turn, f"adapter holds {n} turns but cutoff is {cutoff_turn}"
        q = np.asarray(self.gw.embed([question], "retrieve", "q", query=True)[0], dtype=np.float32)
        q /= np.linalg.norm(q)
        V = np.stack(self.vecs[:n])
        vec = np.argsort(-(V @ q), kind="stable")[:POOL].tolist()
        pool = rrf([vec, self.bm.top(question, POOL)])[:POOL]
        res = self.gw.rerank(question, [doc_text(self.turns[i]) for i in pool], "retrieve", "rr")
        ranked = sorted(res, key=lambda x: -x["relevance_score"])[:TOP_K]
        picks = sorted(pool[x["index"]] for x in ranked)
        recent = list(range(max(0, n - RECENT), n)) if not self.leaky else list(range(max(0, cutoff_turn - RECENT), cutoff_turn))
        blocks = [self.turns[i] for i in picks]
        text = render(blocks, [self.turns[i] for i in recent], now, self.style)
        used = sorted({self.turns[i]["turn"] for i in picks} | {self.turns[i]["turn"] for i in recent})
        return Retrieval(text, used, {"retrieved_turns": [self.turns[i]["turn"] for i in picks],
                                      "pool_turns": [self.turns[i]["turn"] for i in pool]})


# ---------------------------------------------------------------- baselines
class NoHistory(System):
    name = "none"

    def ingest(self, turn):
        pass

    def mark(self):
        return 0

    def rewind(self, token):
        pass

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        return Retrieval(SYS_BASE.split("，")[0] + "。你没有任何过去的聊天记录，请自然地回答用户这句话。", [])


class Vague(System):
    """Always-vague reference: no memory, and the prompt tells the model to answer warmly but without any concrete fact.
    Shows how much a judge rewards 'sounds relevant' answers."""
    name = "vague"

    def ingest(self, turn):
        pass

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        return Retrieval("你是用户长期聊天的伴侣小满。请用一两句温暖、听起来很相关的话回应用户，但不要给出任何具体的事实、日期、名字或数字，也不要下明确的结论。", [])


class RecentN(System):
    def __init__(self, n=6):
        self.n, self.turns, self.name = n, [], f"recent{n}"

    def ingest(self, turn):
        self.turns.append(turn)

    def rewind(self, token):
        del self.turns[token:]

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        rec = self.turns[-self.n:]
        text = "\n\n".join([SYS_BASE, "【最近的对话】"] + [fmt_base(t, now) for t in rec])
        return Retrieval(text, [t["turn"] for t in rec])


class FullContext(System):
    """'Stuff everything': the most recent turns that fit a context budget (window_tokens of memory text).
    M01's whole history is about 167k tokens and M02's about 680k, so late exam points are truncated at the
    oldest end, as a 128k-window model would."""

    TOK_PER_CHAR = 0.70

    def __init__(self, window_tokens=110000):
        self.window, self.turns, self.name = window_tokens, [], "full-context"
        self.sizes = []

    def ingest(self, turn):
        self.turns.append(turn)
        self.sizes.append(len(fmt_base(turn, "")) + 2)

    def rewind(self, token):
        del self.turns[token:]
        del self.sizes[token:]

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        budget = int(self.window / self.TOK_PER_CHAR)
        total, i = 0, len(self.turns)
        while i > 0 and total + self.sizes[i - 1] <= budget:
            total += self.sizes[i - 1]
            i -= 1
        keep = self.turns[i:]
        text = "\n\n".join([SYS_BASE.replace("过去的聊天片段和最近的对话", "全部聊天记录"), "【聊天记录】"] +
                           [fmt_base(t, now) for t in keep])
        return Retrieval(text, [t["turn"] for t in keep], {"first_turn": keep[0]["turn"] if keep else None})


class Bm25Local(System):
    """Local lexical reference: BM25 top-10 over the turns seen so far + the last 6 turns.  Makes no model calls (C = memory text only)."""

    def __init__(self):
        self.turns, self.bm, self.name = [], IncBM25(), "bm25-recent6"

    def ingest(self, turn):
        self.turns.append(turn)
        self.bm.add(doc_text(turn))

    def rewind(self, token):
        del self.turns[token:]
        self.bm.truncate(token)

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        n = len(self.turns)
        picks = sorted(self.bm.top(question, TOP_K))
        end = cutoff_turn if getattr(self, "leaky", False) else n      # leaky = positive control for the sentinel test
        recent = list(range(max(0, end - RECENT), end))
        text = render([self.turns[i] for i in picks], [self.turns[i] for i in recent], now, "base")
        return Retrieval(text, sorted({self.turns[i]["turn"] for i in picks} | {self.turns[i]["turn"] for i in recent}),
                         {"retrieved_turns": [self.turns[i]["turn"] for i in picks]})


NEVER_NOTE = "【这轮的要求】只回应用户当前这句话，不要提任何过去的事，也不要说‘你之前说过’。"
ALWAYS_NOTE = "【这轮的要求】请在回复里自然地带上一件你记得的、和现在最相关的过去的事。"


class TailOnly(System):
    """Natural-use baseline 'never recall': no history at all, only the current conversation tail (turns after the cutoff)."""
    name = "never-recall"

    def __init__(self):
        self.turns, self.tail_from = [], None

    def ingest(self, turn):
        self.turns.append(turn)

    def mark(self):
        return len(self.turns)

    def begin_tail(self):
        self.tail_from = len(self.turns)

    def rewind(self, token):
        del self.turns[token:]
        self.tail_from = None

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        tail = self.turns[self.tail_from:] if self.tail_from is not None else []
        text = (chr(10) * 2).join([SYS_BASE.split("，")[0] + "。你没有任何过去的聊天记录。" + NEVER_NOTE] + (["【当前的对话】"] + [fmt_base(t, now) for t in tail] if tail else []))
        return Retrieval(text, [t["turn"] for t in tail])


class AlwaysRecall(Bm25Local):
    """Natural-use baseline 'recall at every chance': BM25 top-10 + last 6 turns, and the prompt asks to bring up a related old thing."""

    def __init__(self):
        super().__init__()
        self.name = "always-recall"

    def retrieve(self, question, now, cutoff_turn, item_id=None):
        r = super().retrieve(question, now, cutoff_turn, item_id)
        return Retrieval(r.prompt + chr(10) * 2 + ALWAYS_NOTE, r.used_turns, r.meta)


REGISTRY = {
    "qwen-base": lambda gw: QwenRag(gw, "base"),
    "none": lambda gw: NoHistory(),
    "recent6": lambda gw: RecentN(6),
    "full-context": lambda gw: FullContext(),
    "bm25-recent6": lambda gw: Bm25Local(),
    "never-recall": lambda gw: TailOnly(),
    "always-recall": lambda gw: AlwaysRecall(),
    "vague": lambda gw: Vague(),
}
