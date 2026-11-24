"""Retrieval index: inverted terms plus the interval lookup as-of needs.

The write path maintains one row per (term, memory). Search therefore starts from terms
instead of scanning every identity, and as-of selection reads only the candidate revisions
that can be in effect at the instant.
"""
from __future__ import annotations

import json
import re

from .contracts import parse_instant

_TERM = re.compile(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+")

# Issue/PR references and commit-template verbs carry no retrieval signal: every commit has
# a different number, and "fix/update/add" appear in most subjects. They are removed before
# tokenization so a query is won by its distinctive words, not by template syntax.
_REF = re.compile(r"(?i)(?:#|gh-|issue\s+|issues\s+|pr\s+|pull\s+request\s+)\d+")
# Measured on five repositories: stripping issue references alone is neutral, and "update" is
# the only template verb that improved recall without moving any other repository. "add" and
# the rest are kept: they are meaningful in subjects ("Add option X") and dropping them cost
# top-5 ranking on click.
_TEMPLATE = frozenset({"update", "updates", "updated", "updating"})


def as_of(records, instant: str) -> dict | None:
    """The revision in effect at an instant; ties on time resolve to the later revision."""
    target = parse_instant(instant)
    chosen, chosen_key = None, None
    for record in records:
        start = record.get("valid_from") or record.get("effective_at")
        if not start:
            continue
        when = parse_instant(start)
        key = (when, int(record.get("revision") or 0))
        if when <= target and (chosen_key is None or key > chosen_key):
            chosen, chosen_key = record, key
    return chosen


def terms(text: str) -> list[str]:
    """Latin words, CJK characters and CJK bigrams: no segmenter dependency.

    Issue references are stripped before tokenization and commit-template verbs are dropped;
    bare numbers are kept so facts like an age or a version are not lost.
    """
    cleaned = _REF.sub(" ", str(text or "").lower())
    out: list[str] = []
    for match in _TERM.finditer(cleaned):
        token = match.group()
        if token.isascii():
            if token in _TEMPLATE:
                continue
            out.append(token)
        else:
            out.extend(token)
            out.extend(token[index:index + 2] for index in range(max(1, len(token) - 1)))
    return out


def update(db, memory_id: str, *, entity: str, property_name: str, value, revision: int,
           topics=()) -> None:
    """Replace one revision's terms, so an as-of search can reach a superseded value."""
    db.execute("DELETE FROM term_index WHERE memory_id = ? AND revision = ?",
               (memory_id, revision))
    haystack = " ".join((entity, property_name, str(value or ""), " ".join(topics or ())))
    seen = {}
    for term in terms(haystack):
        seen[term] = seen.get(term, 0) + 1
    db.executemany("INSERT OR REPLACE INTO term_index(term, memory_id, revision, weight) "
                   "VALUES(?, ?, ?, ?)",
                   [(term, memory_id, revision, weight) for term, weight in seen.items()])


def update_symbols(db, memory_id: str, symbols, revision: int) -> None:
    """Replace one revision's symbol terms; the second index mirrors ``update``."""
    db.execute("DELETE FROM symbol_index WHERE memory_id = ? AND revision = ?",
               (memory_id, revision))
    seen = {}
    for symbol in symbols or ():
        for term in terms(symbol):
            seen[term] = min(3, seen.get(term, 0) + 1)
    db.executemany("INSERT OR REPLACE INTO symbol_index(term, memory_id, revision, weight) "
                   "VALUES(?, ?, ?, ?)",
                   [(term, memory_id, revision, weight) for term, weight in seen.items()])


def _weighted(db, table: str, wanted: list[str], *, head_only: bool) -> dict[str, float]:
    """Same score formula as ``candidates`` applied to one index table."""
    marks = ",".join("?" * len(wanted))
    source = (f"{table} t JOIN heads h ON h.memory_id = t.memory_id "
              f"AND h.current_revision = t.revision" if head_only else f"{table} t")
    return {row["memory_id"]: float(row["score"]) for row in db.execute(
        f"SELECT t.memory_id AS memory_id, "
        f"SUM(t.weight) * 1.0 / COUNT(DISTINCT t.revision) AS score FROM {source} "
        f"WHERE t.term IN ({marks}) GROUP BY t.memory_id", wanted)}


def _lexical_stats(db, wanted: list[str], *, head_only: bool) -> tuple[int, float]:
    marks = ",".join("?" * len(wanted))
    source = ("term_index t JOIN heads h ON h.memory_id = t.memory_id "
              "AND h.current_revision = t.revision" if head_only else "term_index t")
    row = db.execute(f"SELECT COUNT(*) AS n, MAX(score) AS top FROM ("
                     f"SELECT t.memory_id, SUM(t.weight) * 1.0 / COUNT(DISTINCT t.revision) "
                     f"AS score FROM {source} WHERE t.term IN ({marks}) "
                     f"GROUP BY t.memory_id)", wanted).fetchone()
    return row["n"], float(row["top"] or 0.0)


def symbols_allowed(db, wanted: list[str], *, head_only: bool,
                    gate_k: int = 0, gate_score: float = 0.0) -> bool:
    """Symbols supplement a thin lexical pool; a strong pool keeps its own ordering."""
    if gate_k <= 0 and gate_score <= 0:
        return True
    count, top = _lexical_stats(db, wanted, head_only=head_only)
    return (gate_k > 0 and count < gate_k) or (gate_score > 0 and top < gate_score)


def scores(db, text: str, memory_ids: list[str], *, symbol_weight: float = 0.0,
           symbol_cap: float = 0.0, symbol_gate_k: int = 0,
           symbol_gate_score: float = 0.0) -> dict:
    """Raw term weight plus an optional symbol weight, used only for ordering candidates."""
    wanted = list(dict.fromkeys(terms(text)))
    if not wanted or not memory_ids:
        return {}
    gated = (symbol_weight > 0 and not symbols_allowed(
        db, wanted, head_only=True, gate_k=symbol_gate_k, gate_score=symbol_gate_score))
    out: dict[str, float] = {}
    for table, weight in (("term_index", 1.0), ("symbol_index", symbol_weight)):
        if weight <= 0 or (table == "symbol_index" and gated):
            continue
        marks = ",".join("?" * len(wanted))
        inside = ",".join("?" * len(memory_ids))
        for row in db.execute(f"SELECT memory_id, SUM(weight) AS score FROM {table} "
                              f"WHERE term IN ({marks}) AND memory_id IN ({inside}) "
                              f"GROUP BY memory_id", [*wanted, *memory_ids]):
            value = row["score"]
            if table == "symbol_index" and symbol_cap > 0:
                value = min(value, symbol_cap)
            out[row["memory_id"]] = out.get(row["memory_id"], 0.0) + weight * value
    return out


def candidates(db, text: str, limit: int = 200, *, head_only: bool = True,
               symbol_weight: float = 0.0, symbol_cap: float = 0.0,
               symbol_gate_k: int = 0, symbol_gate_score: float = 0.0) -> list[str]:
    """Ids ordered by summed term weight, plus symbol-index ids when weighted above zero.

    With ``head_only`` false the search covers every revision, so a value later superseded
    is still reachable when the caller wants a past instant; as-of selection then rejects a
    memory that did not exist yet.
    """
    wanted = list(dict.fromkeys(terms(text)))
    if not wanted:
        return []
    use_symbols = symbol_weight > 0 and symbols_allowed(
        db, wanted, head_only=head_only, gate_k=symbol_gate_k,
        gate_score=symbol_gate_score)
    if use_symbols:
        combined = _weighted(db, "term_index", wanted, head_only=head_only)
        for memory_id, score in _weighted(db, "symbol_index", wanted,
                                          head_only=head_only).items():
            if symbol_cap > 0:
                score = min(score, symbol_cap)
            combined[memory_id] = combined.get(memory_id, 0.0) + symbol_weight * score
        ordered = sorted(combined.items(), key=lambda item: (-item[1], item[0]))
        return [memory_id for memory_id, _ in ordered[:limit]]
    marks = ",".join("?" * len(wanted))
    source = ("term_index t JOIN heads h ON h.memory_id = t.memory_id "
              "AND h.current_revision = t.revision" if head_only else "term_index t")
    # Averaging over distinct revisions keeps a long-lived property from outranking a
    # precise one merely because it has been revised many times.
    rows = db.execute(f"SELECT t.memory_id AS memory_id, "
                      f"SUM(t.weight) * 1.0 / COUNT(DISTINCT t.revision) AS score FROM {source} "
                      f"WHERE t.term IN ({marks}) GROUP BY t.memory_id "
                      f"ORDER BY score DESC, t.memory_id LIMIT ?",
                      [*wanted, limit]).fetchall()
    return [row["memory_id"] for row in rows]


def head_numbers(db, memory_ids: list[str]) -> dict[str, int]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    return {row["memory_id"]: row["current_revision"] for row in db.execute(
        f"SELECT memory_id, current_revision FROM heads WHERE memory_id IN ({marks})",
        memory_ids)}


def head_records(db, memory_ids: list[str]) -> dict[str, dict]:
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    return {row["memory_id"]: json.loads(row["data"]) for row in db.execute(
        f"SELECT h.memory_id AS memory_id, r.data AS data FROM heads h "
        f"JOIN revisions r ON r.memory_id = h.memory_id AND r.revision = h.current_revision "
        f"WHERE h.memory_id IN ({marks})", memory_ids)}


def as_of_records(db, memory_ids: list[str], instant: str) -> dict[str, dict]:
    """Pick the revision in effect at the instant for each candidate, in one pass."""
    if not memory_ids:
        return {}
    marks = ",".join("?" * len(memory_ids))
    grouped: dict[str, list[dict]] = {}
    for row in db.execute(f"SELECT memory_id, valid_from, data FROM revisions "
                          f"WHERE memory_id IN ({marks}) ORDER BY memory_id, revision",
                          memory_ids):
        record = json.loads(row["data"])
        if row["valid_from"]:
            record["valid_from"] = row["valid_from"]
        grouped.setdefault(row["memory_id"], []).append(record)
    return {memory_id: as_of(items, instant) for memory_id, items in grouped.items()}


__all__ = ["terms", "update", "update_symbols", "candidates", "scores", "head_numbers",
           "head_records", "as_of_records", "as_of"]
