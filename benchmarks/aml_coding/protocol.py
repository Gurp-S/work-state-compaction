"""AML Coding Track wire mapping: the only file that needs editing when the guide changes.

The official API guide (agentmemoryleaderboard.ai/api-guide) was unavailable when this
adapter was built, so field names are accepted through documented aliases. Semantics are
fixed: Add stores evidence, Search returns ranked evidence, neither generates an answer.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))

from wsc.csm import branch_scope, repo_scope  # noqa: E402
from wsc.csm import symbols as csm_symbols  # noqa: E402

SEARCH_RESULTS_KEY = "results"
DEFAULT_TOP_K = 100
MAX_TOP_K = 1000
MAX_SEARCH_CHARS = 240_000  # ~120k tokens; AML trims overflow text from the tail

_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")


def content_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = [value[key] for key in ("text", "content", "message", "body")
                 if isinstance(value.get(key), str)]
        return "\n".join(part.strip() for part in parts if part.strip())
    if isinstance(value, (list, tuple)):
        return "\n".join(text for text in (content_text(item) for item in value) if text)
    return ""


def canonical_scope(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("repo:"):
        repo = text.split("|", 1)[0][len("repo:"):]
        return repo_scope(repo) + ("|" + text.split("|", 1)[1] if "|" in text else "")
    if text.startswith(("entity", "event:")):
        return text
    return repo_scope(text)


def repo_of(scope: str | None) -> str:
    if not scope:
        return "repo"
    text = scope.split("|", 1)[0]
    return text[len("repo:"):] if text.startswith("repo:") else text


def _item_id(raw: dict, content: str, scope: str | None, commit: str | None) -> str:
    if isinstance(raw.get("id"), str) and raw["id"].strip():
        return raw["id"].strip()
    seed = json.dumps({"content": content, "scope": scope, "commit": commit},
                      ensure_ascii=False, sort_keys=True)
    return "aml:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def item(raw: dict, *, default_scope: str | None = None,
         default_commit: str | None = None) -> dict:
    """One Add item in engine terms: evidence plus an explicit or inferred memory binding."""
    if not isinstance(raw, dict):
        raise ValueError("item_invalid")
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    content = content_text(raw.get("content", raw.get("text", raw.get("value"))))
    if not content:
        raise ValueError("content_missing")
    scope = canonical_scope(raw.get("scope") or meta.get("scope") or default_scope)
    repo = raw.get("repo") or meta.get("repo")
    branch = raw.get("branch") or meta.get("branch")
    if branch:
        scope = branch_scope(repo or repo_of(scope), branch)
    commit = raw.get("commit") or meta.get("commit") or default_commit
    observed_at = (raw.get("observed_at") or raw.get("timestamp")
                   or meta.get("observed_at") or meta.get("timestamp"))
    explicit_slot = raw.get("slot") or meta.get("slot")
    slot = explicit_slot or meta.get("kind") or meta.get("type") or "observation"
    entity = (raw.get("entity") or meta.get("entity") or repo
              or repo_of(scope) or "repo")
    value = raw.get("value") if raw.get("value") is not None else content
    topics = raw.get("topics") or meta.get("topics") or ()
    if isinstance(topics, str):
        topics = [topics]
    symbols = raw.get("symbols") or meta.get("symbols") or ()
    if isinstance(symbols, str):
        symbols = [symbols]
    if not symbols and ("diff --git" in content or "\n@@" in content):
        symbols = csm_symbols.select(csm_symbols.token_counts(content))
    metadata = {**meta, **({"commit": commit} if commit else {}),
                **({"observed_at": observed_at} if observed_at else {})}
    return {"id": _item_id(raw, content, scope, commit),
            "content": content, "value": value, "entity": entity, "slot": slot,
            "property_kind": raw.get("property_kind") or meta.get("property_kind")
            or (None if explicit_slot else "event"),
            "semantic_type": raw.get("semantic_type") or "Fact",
            "scope": scope, "topics": list(topics), "symbols": list(symbols),
            "source_type": raw.get("type") or raw.get("source_type") or "coding",
            "source_ref": raw.get("source_ref") or commit,
            "observed_at": observed_at, "commit": commit, "metadata": metadata}


def search_request(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("search_body_invalid")
    query = (body.get("query") or body.get("q") or body.get("text")
             or body.get("question"))
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query_missing")
    scope = canonical_scope(body.get("scope") or body.get("repo"))
    repo = body.get("repo")
    branch = body.get("branch")
    if branch:
        scope = branch_scope(repo or repo_of(scope), branch)
    at_commit = body.get("at_commit") or body.get("commit")
    as_of = body.get("as_of")
    if not at_commit and isinstance(as_of, str) and _SHA.match(as_of.strip()):
        at_commit, as_of = as_of.strip(), None
    top_k = body.get("top_k") or body.get("limit") or DEFAULT_TOP_K
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        raise ValueError("top_k_invalid")
    top_k = max(1, min(top_k, MAX_TOP_K))
    anchor = (body.get("anchor") or body.get("code")
              or body.get("snippet") or body.get("current_code"))
    if isinstance(anchor, dict):
        anchor = content_text(anchor)
    anchor = str(anchor).strip() if anchor is not None else ""
    return {"query": query.strip(), "top_k": top_k, "scope": scope,
            "scope_chain": not bool(body.get("scope_exact", False)),
            "at_commit": at_commit.strip() if isinstance(at_commit, str) else None,
            "as_of": as_of.strip() if isinstance(as_of, str) else None,
            "anchor": anchor or None, "anchor_terms": 8}


def result_row(row: dict, rank: int) -> dict:
    evidence = row.get("evidence") or []
    excerpt = "\n".join(str(item.get("text") or "")
                        for item in evidence if item.get("text"))
    content = excerpt or str(row.get("value") if row.get("value") is not None else "")
    source_refs = row.get("source_refs") or []
    return {"memory_id": row.get("memory_id"),
            "content": content, "text": content, "value": row.get("value"),
            "score": round(1.0 / (60 + rank), 6),
            "source": {"event_id": source_refs[0] if source_refs else None,
                       "source_type": (evidence[0].get("source_type")
                                       if evidence else row.get("source_type")),
                       "observed_at": (evidence[0].get("observed_at")
                                       if evidence else row.get("valid_from")),
                       "commit": row.get("commit")},
            "metadata": {"entity": row.get("entity"), "slot": row.get("slot"),
                         "property_kind": row.get("property_kind"),
                         "scope": row.get("scope"), "origin_scope": row.get("origin_scope"),
                         "valid_from": row.get("valid_from"), "revision": row.get("revision"),
                         "classification": row.get("classification")},
            "evidence": evidence}


__all__ = ["content_text", "canonical_scope", "repo_of", "item", "search_request",
           "result_row", "SEARCH_RESULTS_KEY", "DEFAULT_TOP_K", "MAX_TOP_K",
           "MAX_SEARCH_CHARS"]
