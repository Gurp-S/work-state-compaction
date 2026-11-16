"""CSM service facade. No task execution, no implicit model calls, no globals."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence

from ..contracts import digest
from .contracts import DEPENDENCY_RELATIONS, require
from . import aliases
from . import assembly
from . import bridge
from . import digests
from . import domain
from . import filters
from . import groups
from . import identity as identities
from . import identity_ops
from . import pending as pendings
from .observation_policy import restates
from .observation_batch import ambiguous_indexes, implicit_same_source_replacement
from . import projection as projections
from . import relations as graph
from . import retrieval, state
from . import shadow
from . import temporal
from . import tree
from . import evolve as controller
from .contracts import (CSMError, Event, MemoryCandidate, MemoryQuery, anchors,
                        parse_instant, validate_candidate, validate_event, validate_query)
from .store import CsmStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CSM:
    """Long-lived memory namespace: identities, versions, evidence, pending bindings."""

    def __init__(self, store: CsmStore, *, clock=None):
        self.store = store
        self.clock = clock or _utc_now

    # -- evidence ---------------------------------------------------------
    def ingest(self, events: Sequence[Event]) -> dict:
        """Append source events idempotently; the same id may not change content."""
        accepted, existing = [], []
        touched = set()
        with self.store.transaction() as db:
            for event in events:
                data = validate_event(event)
                row = db.execute("SELECT digest FROM events WHERE id = ?", (data["id"],)).fetchone()
                if row is not None:
                    require(row["digest"] == digest(data["payload"]), "event_conflict")
                    existing.append(data["id"])
                    continue
                db.execute("INSERT INTO events(id, source_type, source_ref, observed_at, data, digest) "
                           "VALUES(?, ?, ?, ?, ?, ?)",
                           (data["id"], data["source_type"], data["source_ref"],
                            data["observed_at"], data["payload_text"],
                            digest(data["payload"])))
                accepted.append(data["id"])
                touched.add(data["source_type"])
            for source_type in sorted(touched):
                # A reader starts at the beginning; ingest never claims events were consumed.
                db.execute("INSERT OR IGNORE INTO watermarks(source_type, last_seq, updated_at) "
                           "VALUES(?, 0, ?)", (source_type, self.clock()))
        return {"ingested": accepted, "existing": existing}

    def _evidence(self, db, source_ids: tuple[str, ...]) -> str | None:
        marks = ",".join("?" * len(source_ids))
        rows = {row["id"]: row["observed_at"] for row in
                db.execute(f"SELECT id, observed_at FROM events WHERE id IN ({marks})",
                           list(source_ids))}
        missing = [item for item in source_ids if item not in rows]
        require(not missing, "evidence_source_unknown")
        times = [value for value in rows.values() if value]
        return max(times, key=parse_instant) if times else None

    # -- writes -----------------------------------------------------------
    def remember(self, candidates: Sequence[MemoryCandidate], *, producer: str = "model") -> list[dict]:
        """Bind each proposal to an identity and commit its revision, atomically per call."""
        results = []
        with self.store.transaction() as db:
            results = self._remember_batch(db, [validate_candidate(c) for c in candidates],
                                           producer=producer)
        return results

    def _remember_batch(self, db, candidates: list[dict], *, producer: str) -> list[dict]:
        ambiguous = ambiguous_indexes(candidates)
        results = []
        for index, candidate in enumerate(candidates):
            if index not in ambiguous:
                results.append(self._remember_one(db, candidate, producer=producer))
                continue
            self._evidence(db, candidate["source_ids"])
            routing = identities.route(db, candidate)
            target = routing.get("memory_id")
            state.validate_transition(state.head(db, target) if target else None, candidate)
            pending = pendings.open_pending(db, self.store.namespace, candidate,
                {"reason": "observation_operation_ambiguous",
                 "candidate_targets": [target] if target else [],
                 "missing_conditions": ["value_operation"]},
                producer=producer, recorded_at=self.clock())
            results.append({"operation": "DEFER", "memory_id": None, "revision": None,
                            "pending_id": pending["pending_id"], "changed": pending["changed"],
                            "reason": "observation_operation_ambiguous",
                            "missing_conditions": ["value_operation"]})
        return results

    def remember_group(self, candidates: Sequence[MemoryCandidate], *, group_id: str,
                       producer: str = "model") -> dict:
        """Commit one semantic event as a unit (§3.3).

        Members that can be decided commit in one transaction; members that cannot are
        parked as pending. The group record states which half happened, so a partial
        commit is visible rather than silently retried.
        """
        with self.store.transaction() as db:
            settled = groups.get(db, group_id)
            if settled is not None:
                # A settled group is a recorded outcome, not a batch to replay.
                return {"group": {**settled, "changed": False}, "results": []}
            data = [validate_candidate(candidate) for candidate in candidates]
            require(all(item["event_group"] in (None, group_id) for item in data),
                    "event_group_mismatch")
            for item in data:
                item["event_group"] = group_id
            results = self._remember_batch(db, data, producer=producer)
            members = [{"memory_id": item["memory_id"], "revision": item["revision"],
                        "operation": item["operation"]}
                       for item in results if item["operation"] not in ("DEFER",)]
            deferred = [item["pending_id"] for item in results
                        if item["operation"] == "DEFER"]
            status = ("committed" if not deferred
                      else ("partial" if members else "deferred"))
            record = groups.record(db, group_id, members=members, deferred=deferred,
                                   status=status, recorded_at=self.clock())
            return {"group": record, "results": results}

    def _remember_one(self, db, data: dict, *, producer: str) -> dict:
        effective_at = self._evidence(db, data["source_ids"])
        if filters.enabled("alias") and data["intent"] == "auto":
            canonical = aliases.canonical(db, data["entity"])
            if canonical != data["entity"]:
                # One identity per entity, so a confirmed alias does not fork the history.
                data = {**data, "entity": canonical}
        routing = identities.route(db, data)
        if routing["operation"] == "UPDATE" and implicit_same_source_replacement(
                state.head(db, routing["memory_id"]), data,
                allow_restatement=filters.enabled("digest")):
            state.validate_transition(state.head(db, routing["memory_id"]), data)
            pending = pendings.open_pending(db, self.store.namespace, data,
                {"reason": "observation_operation_ambiguous",
                 "candidate_targets": [routing["memory_id"]],
                 "missing_conditions": ["value_operation"]}, producer=producer,
                recorded_at=self.clock())
            return {"operation": "DEFER", "memory_id": None, "revision": None,
                    "pending_id": pending["pending_id"], "changed": pending["changed"],
                    "reason": "observation_operation_ambiguous"}
        if data["intent"] == "enrich":
            require(routing["operation"] == "UPDATE", "memory_identity_unknown")
            enriched = identities.add_topics(db, routing["memory_id"], data["topics"])
            return {"operation": "ENRICH", "memory_id": enriched["memory_id"], "revision": None,
                    "changed": bool(enriched["added_topics"]), "topics": enriched["topics"],
                    "reason": "topic_enrichment"}
        if routing["operation"] == "DEFER":
            record = pendings.open_pending(db, self.store.namespace, data, routing,
                                           producer=producer, recorded_at=self.clock())
            return {"operation": "DEFER", "memory_id": None, "revision": None,
                    "changed": record["changed"], "pending_id": record["pending_id"],
                    "reason": routing["reason"],
                    "candidate_targets": routing.get("candidate_targets", []),
                    "missing_conditions": routing.get("missing_conditions", [])}
        if routing["operation"] == "LINK":
            target = data["link_object"]
            if not target.startswith(("memory:", "node:", "action:")):
                target = graph.memory_ref(target)
            edge = graph.link(db, kind=data["link_kind"],
                              subject=graph.memory_ref(routing["memory_id"]), object=target,
                              contexts=data["contexts"], evidence=data["source_ids"],
                              producer=producer, recorded_at=self.clock())
            if (filters.enabled("relconfirm") and data["link_kind"] in DEPENDENCY_RELATIONS
                    and data["source_ids"]):
                # 依赖边由同轮证据确认：组织边（ABOUT 等）不自动确认，留给后续判断。
                graph.confirm(db, edge["rel_id"], evidence=data["source_ids"],
                              producer=producer, recorded_at=self.clock())
            return {"operation": "LINK", "memory_id": routing["memory_id"], "revision": None,
                    "changed": edge["changed"], "rel_id": edge["rel_id"],
                    "reason": "identity_link"}
        if routing["operation"] == "REINTERPRET":
            rebound = identity_ops.reinterpret(db, routing["memory_id"], data["contexts"],
                                               data["source_ids"], reason=data["reason"],
                                               producer=producer, recorded_at=self.clock())
            return {**rebound, "revision": None}
        restated = False
        if (filters.enabled("digest") and data["intent"] == "auto"
                and routing["operation"] == "UPDATE"):
            head = state.head(db, routing["memory_id"])
            if head is not None and restates(head, data):
                # Canonicalize formatting only. CAS, type/status checks and topic writes
                # still run through the same path as every other observation.
                data = {**data, "value": head["value"]}
                restated = True
        if routing["operation"] == "CREATE":
            memory = identities.create(db, data, producer=producer, recorded_at=self.clock())
        else:
            memory = identities.identity_row(db, routing["memory_id"])
            if data["topics"]:
                identities.add_topics(db, memory["memory_id"], data["topics"])
        written = state.append(db, memory, data, producer=producer, recorded_at=self.clock(),
                               effective_at=effective_at,
                               topics=identities.topics_of(db, memory["memory_id"]))
        if filters.enabled("tree"):
            # 旁路：最小挂载，让 node_id 检索有结构可查；不判定主挂载、不做冲突消解。
            tree.mount(db, written["memory_id"], tree.ROOT_NODE,
                       evidence=data["source_ids"], producer=producer,
                       recorded_at=self.clock())
        return {"operation": written["operation"], "memory_id": written["memory_id"],
                "revision": written["revision"], "changed": written["changed"],
                "reason": ("near_duplicate_observation" if restated and not written["changed"]
                           else written.get("reason", routing["reason"]))}

    def enrich(self, memory_id: str, *, topics: Sequence[str]) -> dict:
        """Add retrieval anchors to an existing identity; no state revision is created."""
        with self.store.transaction() as db:
            return identities.add_topics(db, memory_id, anchors(topics, field="topic"))

    def remember_explicit(self, candidate: MemoryCandidate, *, operation: str | None = None,
                          target_memory_id: str | None = None,
                          binding_source_ids: Sequence[str] = (), producer: str = "model") -> dict:
        """Opt-in per-write attribution; no automatic aliases or old-row migration."""
        from .explicit_write import remember
        return remember(self, candidate, operation=operation, target_memory_id=target_memory_id,
                        binding_source_ids=binding_source_ids, producer=producer)

    def resolve_explicit(self, pending_id: str, *, operation: str | None = None,
                         target_memory_id: str | None = None,
                         binding_source_ids: Sequence[str] = (),
                         expected_revision: int | None = None, producer: str = "model") -> dict:
        """Complete a parked explicit write using caller-declared attribution."""
        from .explicit_write import resolve
        return resolve(self, pending_id, operation=operation, target_memory_id=target_memory_id,
                       binding_source_ids=binding_source_ids, expected_revision=expected_revision,
                       producer=producer)

    def rekey(self, memory_id: str, *, contexts: Sequence[str], evidence: Sequence[str],
              producer: str = "model") -> dict:
        """Declare the context set an identity was missing; requires source evidence."""
        with self.store.transaction() as db:
            return identity_ops.rekey(db, memory_id, contexts, evidence, producer=producer,
                                      recorded_at=self.clock())

    def reinterpret(self, memory_id: str, *, contexts: Sequence[str], evidence: Sequence[str],
                    reason: str, producer: str = "model") -> dict:
        """Correct what an identity's anchors mean when new evidence says so (§7.4)."""
        with self.store.transaction() as db:
            return identity_ops.reinterpret(db, memory_id, contexts, evidence, reason=reason,
                                            producer=producer, recorded_at=self.clock())

    def scope_intersection(self, left: str, right: str) -> dict:
        """§11.3 overlap measurement between two nodes; never a merge decision."""
        with self.store.connect() as db:
            return tree.scope_intersection(db, tree.node(db, left), tree.node(db, right))

    def evolve(self, *, producer: str = "controller", promote_threshold: int = 2,
               window_seconds: float | None = None, limit: int = 100) -> dict:
        """One explicit Tree Evolution Controller pass (§12.3); no background loop."""
        return controller.evolve(self, producer=producer,
                                 promote_threshold=promote_threshold,
                                 window_seconds=window_seconds, limit=limit)

    def assemble(self, query: MemoryQuery, *, max_chars: int = 4000,
                 max_items: int = 20) -> dict:
        """Query, then bound the result for one context window (§13.6)."""
        return assembly.assemble(self.query(query), max_chars=max_chars,
                                 max_items=max_items)

    def recall_evidence(self, text: str, *, limit: int = 15, max_chars: int = 4000,
                        until: str | None = None, record_types=None, exclude_ids=()) -> dict:
        """Budgeted source observations and state; no implicit semantic merges."""
        from .evidence_recall import recall
        with self.store.connect() as db:
            return recall(db, text, limit=limit, max_chars=max_chars, until=until,
                          record_types=record_types, exclude_ids=exclude_ids)

    def source_evidence(self, memory_id: str, *, revision: int, expected_value,
                        limit: int = 3, max_chars: int = 4000, until: str | None = None) -> dict:
        """Inspect an explicit revision's original context; never replace retrieval."""
        from .source_inspection import inspect
        with self.store.connect() as db:
            return inspect(db, memory_id, revision=revision, expected_value=expected_value,
                           limit=limit, max_chars=max_chars, until=until)

    def group(self, group_id: str) -> dict | None:
        with self.store.connect() as db:
            return groups.get(db, group_id)

    def groups(self, *, limit: int = 100, status: str | None = None) -> list[dict]:
        with self.store.connect() as db:
            return groups.listing(db, limit=limit, status=status)

    def ingest_wsc(self, events, *, producer: str = "wsc") -> dict:
        """Append already-recorded WSC events through the bridge (§14.2)."""
        require(isinstance(events, (list, tuple)), "wsc_events_invalid")
        return self.ingest(bridge.events_from_wsc(events))

    def merge(self, target: str, source: str, *, evidence: Sequence[str],
              contexts: Sequence[str] | None = None, producer: str = "model") -> dict:
        """Retire one identity into another with the same entity and slot.

        ``contexts`` optionally converges the survivor's declared context set in the same
        transaction (``None`` keeps the survivor's anchors as they are).
        """
        with self.store.transaction() as db:
            return identity_ops.merge(db, target, source, evidence, contexts=contexts,
                                      producer=producer, recorded_at=self.clock())

    # -- relations --------------------------------------------------------
    def link(self, *, kind: str, subject: str, object: str, contexts: Sequence[str] = (),
             evidence: Sequence[str], confirmed: bool = False,
             producer: str = "model") -> dict:
        """Add one typed edge; a model-proposed edge stays a candidate until confirmed."""
        with self.store.transaction() as db:
            return graph.link(db, kind=kind, subject=subject, object=object,
                              contexts=contexts, evidence=evidence, producer=producer,
                              recorded_at=self.clock(), confirmed=confirmed)

    def confirm_relation(self, rel_id: str, *, evidence: Sequence[str],
                         producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return graph.confirm(db, rel_id, evidence=evidence, producer=producer,
                                 recorded_at=self.clock())

    def set_truth(self, rel_id: str, truth: str, *, evidence: Sequence[str] = (),
                  producer: str = "model") -> dict:
        """Record TRUE/FALSE/UNKNOWN on a constraint; UNKNOWN needs no new evidence."""
        with self.store.transaction() as db:
            return graph.set_truth(db, rel_id, truth, evidence=evidence, producer=producer,
                                   recorded_at=self.clock())

    def relations(self, ref: str, *, kinds: Sequence[str] = (), direction: str = "both",
                  confirmed_only: bool = False) -> list[dict]:
        with self.store.connect() as db:
            return graph.of_ref(db, ref, kinds=kinds, direction=direction,
                                confirmed_only=confirmed_only)

    def expand(self, origins: Sequence[str], *, depth: int = 1, kinds: Sequence[str] = ()) -> dict:
        with self.store.connect() as db:
            return graph.expand(db, origins, depth=depth, kinds=kinds, confirmed_only=True)

    def impact(self, memory_id: str) -> dict:
        """What this memory's state change touches; proposals only, never state moves."""
        with self.store.connect() as db:
            return domain.impact(db, memory_id)

    # -- state tree -------------------------------------------------------
    def create_node(self, *, name: str, node_type: str = "organization",
                    parent_id: str | None = None, entity_anchor: str | None = None,
                    scope_description: str | None = None,
                    accepted_relations: Sequence[str] = (), context_constraints: Sequence[str] = (),
                    evidence: Sequence[str] = (), status: str | None = None,
                    producer: str = "model") -> dict:
        from .store import ROOT_NODE
        with self.store.transaction() as db:
            return tree.create_node(db, name=name, node_type=node_type,
                                    parent_id=parent_id or ROOT_NODE,
                                    entity_anchor=entity_anchor,
                                    scope_description=scope_description,
                                    accepted_relations=accepted_relations,
                                    context_constraints=context_constraints,
                                    evidence=evidence, status=status, producer=producer,
                                    recorded_at=self.clock())

    def mount(self, memory_id: str, *, node_id: str | None = None,
              relation: str | None = None, evidence: Sequence[str] = (),
              candidates: Sequence[str] = (), allow_candidate: bool = False,
              producer: str = "model") -> dict:
        """Attach a memory to a node; an undecidable attribution is parked as pending."""
        with self.store.transaction() as db:
            if node_id is None:
                return tree.mount_or_defer(db, self.store.namespace, memory_id,
                                           candidates=candidates, evidence=evidence,
                                           producer=producer, recorded_at=self.clock())
            return tree.mount(db, memory_id, node_id, relation=relation, evidence=evidence,
                              producer=producer, recorded_at=self.clock(),
                              allow_candidate=allow_candidate)

    def resolve_mount(self, pending_id: str, *, node_id: str,
                      producer: str = "model") -> dict:
        """Bind a parked mount once the node is known; then perform the mount."""
        with self.store.transaction() as db:
            item = pendings.get(db, pending_id)
            require(item["pending_type"] == "mount", "pending_type_mismatch")
            require(item["status"] == "pending", "pending_already_settled")
            mounted = tree.mount(db, item["memory_id"], node_id, evidence=item["source_refs"],
                                 producer=producer, recorded_at=self.clock())
            settled = pendings.settle_mount(db, pending_id, node_id=node_id,
                                            recorded_at=self.clock())
            return {**mounted, "pending_id": pending_id, "status": settled["status"]}

    def promote(self, node_id: str, *, evidence: Sequence[str] = (), threshold: int = 2,
                window_seconds: float | None = None, producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return tree.promote(db, node_id, evidence=evidence, threshold=threshold,
                                window_seconds=window_seconds, producer=producer,
                                recorded_at=self.clock())

    def update_contract(self, node_id: str, **changes) -> dict:
        with self.store.transaction() as db:
            return tree.update_contract(db, node_id, producer=changes.pop("producer", "model"),
                                        recorded_at=self.clock(), **changes)

    def retire_node(self, node_id: str, *, evidence: Sequence[str] = (),
                    producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return tree.retire(db, node_id, evidence=evidence, producer=producer,
                               recorded_at=self.clock())

    def merge_nodes(self, source: str, target: str, *, evidence: Sequence[str] = (),
                    producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return tree.merge_nodes(db, source, target, evidence=evidence, producer=producer,
                                    recorded_at=self.clock())

    def split_node(self, source: str, assignments: dict, *, evidence: Sequence[str] = (),
                   producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return tree.split_node(db, source, assignments, evidence=evidence, producer=producer,
                                   recorded_at=self.clock())

    def shadow(self, operations: Sequence[dict]) -> dict:
        """Rehearse structural operations on a candidate tree; nothing is published."""
        with self.store.connect() as db:
            return shadow.evaluate(db, list(operations))

    def shadow_apply(self, operations: Sequence[dict], *, producer: str = "model") -> dict:
        """Rehearse, refuse on invariant violations, then publish in one transaction."""
        with self.store.transaction() as db:
            return shadow.apply(db, list(operations), recorded_at=self.clock(), producer=producer)

    def propose_merge(self, source: str, target: str, *, reason: str = "tree_merge_proposed",
                      producer: str = "model") -> dict:
        with self.store.transaction() as db:
            return tree.propose_merge(db, source, target, reason=reason, producer=producer,
                                      recorded_at=self.clock())

    def publish_operation(self, op_id: int) -> dict:
        with self.store.transaction() as db:
            return tree.publish_op(db, op_id, recorded_at=self.clock())

    def tree(self) -> dict:
        with self.store.connect() as db:
            return tree.tree(db)

    def paths(self, memory_id: str) -> list[dict]:
        with self.store.connect() as db:
            return tree.paths_of(db, memory_id)

    # -- watermarks -------------------------------------------------------
    def watermark(self) -> dict:
        with self.store.connect() as db:
            rows = db.execute("SELECT source_type, last_seq, updated_at FROM watermarks "
                              "ORDER BY source_type")
            available = {row["source_type"]: row["seq"] for row in
                         db.execute("SELECT source_type, MAX(seq) AS seq FROM events "
                                    "GROUP BY source_type")}
            return {"watermarks": [{"source_type": row["source_type"],
                                    "last_seq": row["last_seq"],
                                    "available": available.get(row["source_type"], 0),
                                    "updated_at": row["updated_at"]} for row in rows]}

    def advance_watermark(self, source_type: str, seq: int) -> dict:
        """Move the read cursor forward only: replaying consumed events is never silent."""
        require(isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0,
                "watermark_invalid")
        with self.store.transaction() as db:
            row = db.execute("SELECT last_seq FROM watermarks WHERE source_type = ?",
                             (source_type,)).fetchone()
            current = 0 if row is None else row["last_seq"]
            require(seq >= current, "watermark_regression")
            db.execute("INSERT INTO watermarks(source_type, last_seq, updated_at) VALUES(?, ?, ?) "
                       "ON CONFLICT(source_type) DO UPDATE SET last_seq = excluded.last_seq, "
                       "updated_at = excluded.updated_at", (source_type, seq, self.clock()))
            return {"source_type": source_type, "last_seq": seq, "previous": current,
                    "changed": seq != current}

    def since(self, source_type: str, *, limit: int = 100) -> dict:
        """Events a consumer has not marked consumed yet, oldest first."""
        require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0,
                "query_limit_invalid")
        with self.store.connect() as db:
            row = db.execute("SELECT last_seq FROM watermarks WHERE source_type = ?",
                             (source_type,)).fetchone()
            cursor = 0 if row is None else row["last_seq"]
            rows = db.execute("SELECT seq, id, source_type, source_ref, observed_at, data FROM "
                              "events WHERE source_type = ? AND seq > ? ORDER BY seq LIMIT ?",
                              (source_type, cursor, limit)).fetchall()
            return {"source_type": source_type, "after_seq": cursor,
                    "events": [{"seq": item["seq"], "id": item["id"],
                                "source_ref": item["source_ref"],
                                "observed_at": item["observed_at"],
                                "payload": json.loads(item["data"])} for item in rows]}

    # -- proposals --------------------------------------------------------
    def propose_identity_operations(self, *, producer: str = "model") -> list[dict]:
        """Scan for identities whose anchors disagree with a live sibling; propose, never apply."""
        proposals = []
        with self.store.transaction() as db:
            rows = db.execute("SELECT data FROM identities WHERE contexts = '[]' "
                              "ORDER BY memory_id")
            for row in rows:
                data = json.loads(row["data"])
                if data.get("merged_into"):
                    continue
                variants = [item for item in identities.siblings(db, data["entity"], data["slot"])
                            if item["memory_id"] != data["memory_id"] and item["contexts"]]
                if not variants:
                    continue
                if len(variants) == 1:
                    target = variants[0]
                    proposal = {"operation": "MERGE", "memory_id": target["memory_id"],
                                "source": data["memory_id"], "contexts": target["contexts"],
                                "reason": "identity_context_variant_exists",
                                "candidate_targets": [target["memory_id"]],
                                "source_refs": data.get("identity_evidence", []),
                                "entity": data["entity"], "slot": data["slot"]}
                else:
                    proposal = {"operation": "MERGE", "memory_id": None,
                                "source": data["memory_id"], "contexts": [],
                                "reason": "identity_ambiguous_variants",
                                "candidate_targets": [item["memory_id"] for item in variants],
                                "missing_conditions": ["context_anchor"],
                                "source_refs": data.get("identity_evidence", []),
                                "entity": data["entity"], "slot": data["slot"]}
                proposals.append(pendings.open_identity_operation(
                    db, self.store.namespace, proposal, producer=producer,
                    recorded_at=self.clock()))
        return proposals

    def apply_proposal(self, pending_id: str, *, producer: str = "model") -> dict:
        """Apply one stored identity proposal, refusing incomplete ones instead of guessing."""
        with self.store.transaction() as db:
            item = pendings.get(db, pending_id)
            require(item["pending_type"] == "identity_operation", "pending_type_mismatch")
            require(item["status"] == "pending", "pending_already_settled")
            require(not item["missing_conditions"], "proposal_incomplete")
            if item["operation"] == "MERGE":
                result = identity_ops.merge(db, item["memory_id"], item["source"],
                                            item["source_refs"], contexts=item["contexts"],
                                            producer=producer, recorded_at=self.clock())
            elif item["operation"] == "REKEY":
                result = identity_ops.rekey(db, item["memory_id"], item["contexts"],
                                            item["source_refs"], producer=producer,
                                            recorded_at=self.clock())
            else:
                raise CSMError("proposal_operation_unknown")
            settled = pendings.settle(db, pending_id, memory_id=result["memory_id"],
                                      recorded_at=self.clock())
            return {**result, "pending_id": pending_id, "status": settled["status"]}

    def resolve_pending(self, pending_id: str, *, contexts: Sequence[str] = (),
                        producer: str = "model", operation: str | None = None) -> dict:
        """Bind a pending attribution once the missing anchor (or identity) is known."""
        with self.store.transaction() as db:
            item = pendings.get(db, pending_id)
            require(item["pending_type"] == "identity", "pending_type_mismatch")
            require(item["status"] == "pending", "pending_already_settled")
            require(operation in (None, "create", "update"), "pending_operation_invalid")
            if "value_operation" in item.get("missing_conditions", []) and operation is None:
                return {"pending_id": pending_id, "status": "pending",
                        "reason": item["reason"], "missing_conditions": ["value_operation"]}
            data = validate_candidate(MemoryCandidate(
                entity=item["entity"], slot=item["slot"],
                value=item["semantic_payload"]["value"],
                semantic_type=item["semantic_payload"]["semantic_type"],
                contexts=tuple(contexts), topics=tuple(item["semantic_payload"]["topics"]),
                status=item["semantic_payload"]["status"],
                lifecycle=item["semantic_payload"]["lifecycle"],
                source_ids=tuple(item["source_refs"]), intent=operation or "auto"))
            effective_at = self._evidence(db, data["source_ids"])
            routing = identities.route(db, data)
            if operation == "create":
                require(routing["operation"] == "CREATE", "pending_create_identity_exists")
            if routing["operation"] == "DEFER":
                return {"pending_id": pending_id, "status": "pending",
                        "reason": routing["reason"],
                        "candidate_targets": routing.get("candidate_targets", []),
                        "missing_conditions": routing.get("missing_conditions", [])}
            if routing["operation"] == "CREATE":
                memory = identities.create(db, data, producer=producer, recorded_at=self.clock())
            else:
                memory = identities.identity_row(db, routing["memory_id"])
                if data["topics"]:
                    identities.add_topics(db, memory["memory_id"], data["topics"])
            written = state.append(db, memory, data, producer=producer, recorded_at=self.clock(),
                                   effective_at=effective_at,
                                   topics=identities.topics_of(db, memory["memory_id"]))
            settled = pendings.settle(db, pending_id, memory_id=written["memory_id"],
                                      recorded_at=self.clock())
            return {"pending_id": pending_id, "status": settled["status"],
                    "memory_id": written["memory_id"], "revision": written["revision"],
                    "operation": written["operation"], "changed": written["changed"]}

    # -- reads ------------------------------------------------------------
    def query(self, query: MemoryQuery) -> dict:
        with self.store.connect() as db:
            return retrieval.query(db, validate_query(query))

    def search(self, text: str, *, limit: int = 20, hops: int = 1,
               diverse: bool = False, window: tuple[str | None, str | None] | None = None) -> dict:
        """Free-text candidate discovery, a fallback when identity and topics are unknown.

        ``window`` restricts validity the same way ``MemoryQuery.valid_at`` does, so a caller
        that asks "as of then" does not spend its budget on memories from later turns.
        """
        with self.store.connect() as db:
            return retrieval.search(db, text, limit=limit, hops=hops, diverse=diverse,
                                    window=window)

    def timeline(self, memory_id: str, *, start: str | None = None,
                 end: str | None = None) -> dict:
        """The revisions whose validity intersects a window, ordered by when they held."""
        with self.store.connect() as db:
            history = retrieval.read(db, memory_id, history=True).get("history", [])
            return {"memory_id": memory_id, "window": list(temporal.window(start, end)),
                    "revisions": temporal.between(history, start, end)}

    def aliases(self, *, entity: str | None = None, include_proposals: bool = True) -> dict:
        """Confirmed names for an entity, plus the unconfirmed candidates that suggest more."""
        require(type(include_proposals) is bool, 'alias_proposal_option_invalid')
        with self.store.connect() as db:
            return {"entity": entity,
                    "names": aliases.links(db, entity) if entity else [],
                    "canonical": aliases.canonical(db, entity) if entity else None,
                    "proposals": aliases.proposals(db) if include_proposals else []}

    def confirm_alias(self, alias: str, entity: str, *, evidence: Sequence[str],
                      kind: str = "explicit_marker") -> dict:
        with self.store.transaction() as db:
            return aliases.confirm(db, alias, entity, evidence, kind=kind,
                                   recorded_at=self.clock())

    def digest(self, memory_id: str, *, keep: int = 12) -> dict:
        """Fold superseded revisions into a mechanical digest; revisions stay readable."""
        with self.store.transaction() as db:
            return digests.compact(db, memory_id, recorded_at=self.clock(), keep=keep)

    def memory(self, memory_id: str, *, history: bool = False) -> dict:
        with self.store.connect() as db:
            return retrieval.read(db, memory_id, history=history)

    def pending(self, *, limit: int = 100) -> list[dict]:
        with self.store.connect() as db:
            return pendings.listing(db, limit=limit)

    def rebuild(self) -> dict:
        """Recompute projections; never rewrites a committed revision."""
        with self.store.transaction() as db:
            return projections.rebuild(db)

    def status(self) -> dict:
        with self.store.connect() as db:
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("events", "identities", "revisions", "heads", "projection",
                                    "pending", "identity_changes", "relations", "tree_nodes",
                                    "tree_mounts", "tree_ops")}
            counts["pending_open"] = db.execute(
                "SELECT COUNT(*) FROM pending WHERE status = 'pending'").fetchone()[0]
            counts["tree_revision"] = tree.head(db)
        return {"namespace": self.store.namespace, **counts}


__all__ = ["CSM", "CsmStore", "CSMError", "Event", "MemoryCandidate", "MemoryQuery"]
