"""Vector recall for candidate discovery (opt-in, §13.3).

The default embedder is a deterministic character n-gram hashing vectorizer: no model download,
no network, stable across runs. A real semantic embedder can be plugged in through an
OpenAI-compatible `/embeddings` endpoint. Both paths produce L2-normalised vectors, so cosine
similarity is a dot product.

Enable with ``WSC_CSM_RECALL=vector`` (``WSC_CSM_EMBEDDER=char|http``, default ``char``).
Anything else keeps the lexical fallback in ``retrieval.search``.
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from .recall_policy import MODES, mode
from .recall_cache import content_signature, database_key

DIM = int(os.environ.get("WSC_CSM_VECTOR_DIM", "512"))


def enabled() -> bool:
    return mode() in ("vector", "hybrid")


class CharNgramEmbedder:
    """Hashed character 2-3 gram counts, L2-normalised. Deterministic and dependency-free."""

    def __init__(self, dim: int = DIM, ngrams: tuple[int, ...] = (2, 3)):
        self.dim = dim
        self.ngrams = ngrams

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for size in self.ngrams:
            for index in range(max(0, len(text) - size + 1)):
                gram = text[index:index + size]
                if gram.strip():
                    digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                    vector[int.from_bytes(digest, "big") % self.dim] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vector(text) for text in texts])


class HttpEmbedder:
    """Any OpenAI-compatible embeddings endpoint; vectors are normalised locally."""

    def __init__(self, base_url: str, model: str, key: str | None = None):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self.key = key

    def embed(self, texts: list[str]) -> np.ndarray:
        import requests

        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        response = requests.post(self.url, headers=headers,
                                 json={"model": self.model, "input": texts}, timeout=120)
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda row: row.get("index", 0))
        matrix = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


class FastEmbedder:
    """Local ONNX sentence embedder (fastembed). The model lives under WSC_CSM_EMBED_CACHE."""

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5", cache_dir: str | None = None):
        self.model_name = model
        self.cache_dir = cache_dir or os.environ.get("WSC_CSM_EMBED_CACHE", "E:/models/fastembed")
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir,
                                        providers=["CPUExecutionProvider"])
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        matrix = np.asarray(list(self.model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def query(self, text: str) -> np.ndarray:
        return self.query_batch([text])

    def query_batch(self, texts: list[str]) -> np.ndarray:
        matrix = np.asarray(list(self.model.query_embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


def default_embedder():
    choice = os.environ.get("WSC_CSM_EMBEDDER", "char").strip().lower()
    if choice == "http":
        base = os.environ.get("WSC_CSM_EMBED_URL")
        if not base:
            raise RuntimeError("WSC_CSM_EMBED_URL is required when WSC_CSM_EMBEDDER=http")
        return HttpEmbedder(base, os.environ.get("WSC_CSM_EMBED_MODEL", "text-embedding-3-small"),
                            os.environ.get("WSC_CSM_EMBED_KEY"))
    if choice == "fastembed":
        return FastEmbedder(os.environ.get("WSC_CSM_EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
                            os.environ.get("WSC_CSM_EMBED_CACHE"))
    return CharNgramEmbedder()


def _texts(db) -> tuple[list[str], list[dict]]:
    from .. import identity as identities
    from .. import state

    texts, rows = [], []
    for row in db.execute("SELECT memory_id, data FROM identities").fetchall():
        identity = json.loads(row["data"])
        if identity.get("merged_into"):
            continue
        record = state.head(db, row["memory_id"])
        if record is None:
            continue
        topics = identities.topics_of(db, row["memory_id"])
        texts.append(" ".join((identity["entity"], identity["slot"], str(record["value"] or ""),
                               " ".join(topics))))
        rows.append({"identity": identity, "record": record})
    return texts, rows


_EMBEDDER = None
_CACHE: dict[tuple, tuple[str, np.ndarray]] = {}


def _order(rows: list[dict], scores, limit: int) -> list[int]:
    """Rank by score, then by memory_id.

    ``argsort`` alone resolves equal scores by array position, and the two embedding paths
    order their rows differently, so ties used to pick different winners for the same query.
    """
    def key(index: int):
        return (-float(scores[index]), rows[int(index)]["identity"]["memory_id"])

    return sorted(range(len(scores)), key=key)[:limit]


def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = default_embedder()
    return _EMBEDDER


def search(db, text: str, limit: int = 20, **anchors) -> dict:
    """Cosine ranking over live identities; same result shape as the lexical search."""
    from . import filters
    from .. import retrieval

    if filters.enabled("index"):
        from . import index_store

        return index_store.search(db, text, limit=limit, **anchors)
    texts, rows = _texts(db)
    if not rows:
        return {"query": {"text": text}, "results": [], "counts": {}}
    embedder = _embedder()
    key = database_key(db)
    signature = content_signature(rows, embedder)
    cached = _CACHE.get(key)
    if cached is None or cached[0] != signature:
        cached = (signature, embedder.embed(texts))
        _CACHE[key] = cached
    # Metadata always comes from the authoritative read, even when vectors are reused.
    matrix = cached[1]
    if filters.enabled("filters") and any(value is not None for value in anchors.values()):
        # Anchors are filters in every mode; dropping them here spent the limit on
        # memories the caller had already excluded. Applied to the cached matrix so a
        # narrowed query never shrinks what later queries can see.
        mask = [filters.keep(retrieval._anchors(row["identity"], row["record"]), **anchors)[0]
                for row in rows]
        if not any(mask):
            return {"query": {"text": text}, "results": [], "counts": {}}
        rows = [row for row, ok in zip(rows, mask) if ok]
        matrix = matrix[[index for index, ok in enumerate(mask) if ok]]
    if hasattr(embedder, "query"):
        query_vector = embedder.query(text)[0]
    else:
        query_vector = embedder.embed([text])[0]
    scores = matrix @ query_vector
    order = _order(rows, scores, limit)
    results = []
    for index in order:
        if scores[index] <= 0:
            continue
        row = rows[int(index)]
        item = retrieval._view(db, row["identity"], row["record"])
        item.update({"classification": "CURRENT_CONFIRMED", "confirmed": True,
                     "reason": "vector_match", "score": round(float(scores[index]), 4),
                     "uncertainty": {"classification": "CURRENT_CONFIRMED", "confirmed": True,
                                     "missing_conditions": []}})
        results.append(item)
    return {"query": {"text": text}, "results": results,
            "counts": {"CURRENT_CONFIRMED": len(results)}}
