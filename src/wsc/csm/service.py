"""CSM core: events, engine-owned property identities, revisions, evidence retrieval.

There is no write-time pending pool and no semantic similarity: a candidate binds to a
property record, a state property updates, an event property appends at its own observation
scope. Retrieval returns the source evidence alongside the memory row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence

from ..contracts import digest
from . import assembly, commits, consolidation, index, retrieval
from . import identity as identities
from . import properties
from . import state
from .contracts import (CSMError, Event, MemoryCandidate, MemoryQuery, parse_instant, require,
                        validate_candidate, validate_event, validate_query)
from .store import CsmStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CSM:
    """Long-lived memory namespace over one event log."""

    def __init__(self, store: CsmStore, *, clock=None):
        self.store = store
        self.clock = clock or _utc_now

    # -- evidence ---------------------------------------------------------
    def ingest(self, events: Sequence[Event]) -> dict:
        accepted, existing, redacted = [], [], 0
        with self.store.transaction() as db:
            for event in events:
                data = validate_event(event)
                row = db.execute("SELECT digest FROM events WHERE id = ?", (data["id"],)).fetchone()
                if row is not None:
                    require(row["digest"] == digest(data["payload"]), "event_conflict")
                    existing.append(data["id"])
                    continue
                metadata = json.dumps(data["metadata"], sort_keys=True, ensure_ascii=False)
                db.execute("INSERT INTO events(id, source_type, source_ref, observed_at, data, "
                           "digest, metadata) VALUES(?, ?, ?, ?, ?, ?, ?)",
                           (data["id"], data["source_type"], data["source_ref"],
                            data["observed_at"], data["payload_text"],
                            digest(data["payload"]), metadata))
                sha = commits.key(data["metadata"])
                if sha and data["observed_at"]:
                    commits.register(db, sha, data["observed_at"], data["metadata"])
                redacted += data["redacted"]
                accepted.append(data["id"])
        return {"ingested": accepted, "existing": existing, "redacted": redacted}

    def _evidence(self, db, source_ids: tuple[str, ...]) -> tuple[str | None, str | None]:
        """Latest source instant plus the commit it belongs to, never a caller guess."""
        marks = ",".join("?" * len(source_ids))
        rows = {row["id"]: row for row in
                db.execute(f"SELECT id, observed_at, metadata FROM events WHERE id IN ({marks})",
                           list(source_ids))}
        missing = [item for item in source_ids if item not in rows]
        require(not missing, "evidence_source_unknown")
        best, best_key = None, None
        for position, source_id in enumerate(source_ids):
            row = rows[source_id]
            if not row["observed_at"]:
                continue
            key = (parse_instant(row["observed_at"]), position)
            if best_key is None or key > best_key:
                best, best_key = row, key
        if best is None:
            return None, None
        metadata = json.loads(best["metadata"]) if best["metadata"] else {}
        return best["observed_at"], commits.key(metadata)

    # -- writes -----------------------------------------------------------
    def remember(self, candidates: Sequence[MemoryCandidate], *, producer: str = "model") -> list[dict]:
        with self.store.transaction() as db:
            return [self._remember_one(db, validate_candidate(item), producer=producer)
                    for item in candidates]

    def _remember_one(self, db, data: dict, *, producer: str) -> dict:
        effective_at, commit = self._evidence(db, data["source_ids"])
        if data["intent"] == "enrich":
            routing = identities.route(db, data, recorded_at=self.clock())
            enriched = identities.add_topics(db, routing["memory_id"], data["topics"])
            identities.add_symbols(db, routing["memory_id"], data["symbols"])
            head = state.head(db, routing["memory_id"])
            if head is not None:
                index.update(db, routing["memory_id"], entity=data["entity"],
                             property_name=identities.identity_row(
                                 db, routing["memory_id"])["slot"],
                             value=head["value"], revision=head["revision"],
                             topics=enriched["topics"])
                index.update_symbols(db, routing["memory_id"],
                                     identities.symbols_of(db, routing["memory_id"]),
                                     head["revision"])
            return {"operation": "ENRICH", "memory_id": routing["memory_id"],
                    "revision": None, "changed": bool(enriched["added_topics"]),
                    "topics": enriched["topics"], "reason": "topic_enrichment"}
        routing = identities.route(db, data, recorded_at=self.clock())
        if routing["operation"] == "CREATE":
            memory = identities.create(db, data, routing["property"], routing["scope"],
                                       origin_scope=routing["origin_scope"],
                                       producer=producer, recorded_at=self.clock())
        else:
            memory = identities.identity_row(db, routing["memory_id"])
            if data["topics"]:
                identities.add_topics(db, memory["memory_id"], data["topics"])
            if data["symbols"]:
                identities.add_symbols(db, memory["memory_id"], data["symbols"])
        written = state.append(db, memory, data, producer=producer, recorded_at=self.clock(),
                               effective_at=effective_at,
                               topics=identities.topics_of(db, memory["memory_id"]),
                               symbols=identities.symbols_of(db, memory["memory_id"]),
                               commit=commit)
        return {"operation": written["operation"], "memory_id": memory["memory_id"],
                "revision": written["revision"], "changed": written["changed"],
                "property_id": memory["property_id"], "property_kind": memory["property_kind"],
                "scope": memory["scope"], "origin_scope": routing["origin_scope"],
                "reason": routing["reason"], **({"commit": commit} if commit else {})}

    def enrich(self, memory_id: str, *, topics: Sequence[str]) -> dict:
        with self.store.transaction() as db:
            from .contracts import anchors
            enriched = identities.add_topics(db, memory_id, anchors(topics, field="topic"))
            head = state.head(db, memory_id)
            item = identities.identity_row(db, memory_id)
            if head is not None:
                index.update(db, memory_id, entity=item["entity"], property_name=item["slot"],
                             value=head["value"], revision=head["revision"],
                             topics=enriched["topics"])
                index.update_symbols(db, memory_id, identities.symbols_of(db, memory_id),
                                     head["revision"])
            return enriched

    def consolidate(self) -> dict:
        with self.store.transaction() as db:
            return consolidation.run(db, recorded_at=self.clock())

    def alias_property(self, property_id: str, alias: str) -> dict:
        with self.store.transaction() as db:
            return properties.add_alias(db, property_id, alias)

    # -- reads ------------------------------------------------------------
    def query(self, query: MemoryQuery) -> dict:
        with self.store.connect() as db:
            return retrieval.query(db, validate_query(query))

    def search(self, text: str, *, limit: int = 20, window=None, entity: str | None = None,
               scope: str | None = None, scope_chain: bool = False,
               at_commit: str | None = None, with_evidence: bool = True,
               anchor: str | None = None, anchor_terms: int = 8) -> dict:
        with self.store.connect() as db:
            return retrieval.search(db, text, limit=limit, window=window, entity=entity,
                                    scope=scope, scope_chain=scope_chain,
                                    at_commit=at_commit, with_evidence=with_evidence,
                                    anchor=anchor, anchor_terms=anchor_terms)

    def timeline(self, memory_id: str, *, start: str | None = None,
                 end: str | None = None) -> dict:
        with self.store.connect() as db:
            history = retrieval.read(db, memory_id, history=True).get("history", [])
            start_at = parse_instant(start) if start else None
            end_at = parse_instant(end) if end else None
            selected = []
            for item in history:
                at = parse_instant(item["valid_from"])
                if (start_at is None or at >= start_at) and (end_at is None or at <= end_at):
                    selected.append(item)
            return {"memory_id": memory_id, "revisions": selected}

    def properties(self, entity: str) -> list[dict]:
        with self.store.connect() as db:
            return properties.for_entity(db, entity)

    def memory(self, memory_id: str, *, history: bool = False) -> dict:
        with self.store.connect() as db:
            return retrieval.read(db, memory_id, history=history)

    def context(self, result: dict, *, max_chars: int = 4000, max_items: int = 20) -> dict:
        """Budgeted context block over any query/search result packet."""
        return assembly.assemble(result, max_chars=max_chars, max_items=max_items)

    def status(self) -> dict:
        with self.store.connect() as db:
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("events", "commits", "properties", "identities",
                                    "memory_topics", "memory_symbols", "revisions", "heads",
                                    "term_index", "symbol_index")}
        return {"namespace": self.store.namespace, **counts}

    def rebuild(self) -> dict:
        """Recompute both indexes from revisions and memory symbols; facts are never rewritten."""
        count = 0
        with self.store.transaction() as db:
            db.execute("DELETE FROM symbol_index")
            for row in db.execute("SELECT data FROM identities ORDER BY memory_id"):
                item = json.loads(row["data"])
                topics = identities.topics_of(db, item["memory_id"])
                symbols = identities.symbols_of(db, item["memory_id"])
                for record in state.revisions(db, item["memory_id"]):
                    index.update(db, item["memory_id"], entity=item["entity"],
                                 property_name=item["slot"], value=record["value"],
                                 revision=record["revision"], topics=topics)
                    index.update_symbols(db, item["memory_id"], symbols, record["revision"])
                    count += 1
        return {"indexed_revisions": count}


__all__ = ["CSM", "CsmStore", "CSMError", "Event", "MemoryCandidate", "MemoryQuery", "assembly"]
