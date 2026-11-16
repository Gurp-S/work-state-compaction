"""One explicitly bound memory namespace per SQLite file; all mutations are serialized.

The CSM namespace is a long-lived memory space, so it is deliberately not a WSC
session binding: WSC's session/workspace identity is not a memory namespace (§2.4).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from ..contracts import encode, identifier
from .contracts import require
from .contracts import IDENTITY_KEY_RULE

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 source_type TEXT NOT NULL, source_ref TEXT, observed_at TEXT,
 data TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identities (
 memory_id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE,
 entity TEXT NOT NULL, slot TEXT NOT NULL, contexts TEXT NOT NULL,
 semantic_type TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS identity_entity_slot ON identities(entity, slot);
CREATE TABLE IF NOT EXISTS memory_topics (
 memory_id TEXT NOT NULL, topic TEXT NOT NULL, PRIMARY KEY(memory_id, topic));
CREATE TABLE IF NOT EXISTS revisions (
 memory_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY (memory_id, revision));
CREATE TABLE IF NOT EXISTS heads (
 memory_id TEXT PRIMARY KEY, current_revision INTEGER NOT NULL,
 projection_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS projection (memory_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending (
 pending_id TEXT PRIMARY KEY, pending_type TEXT NOT NULL, status TEXT NOT NULL,
 entity TEXT, slot TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identity_changes (
 change_id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
 kind TEXT NOT NULL, recorded_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identity_aliases (
 identity_key TEXT PRIMARY KEY, memory_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relations (
 rel_id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, object TEXT NOT NULL,
 contexts TEXT NOT NULL, confirmed INTEGER NOT NULL, truth TEXT, evidence TEXT NOT NULL,
 producer TEXT NOT NULL, recorded_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS relation_subject ON relations(subject, kind);
CREATE INDEX IF NOT EXISTS relation_object ON relations(object, kind);
CREATE TABLE IF NOT EXISTS tree_nodes (
 node_id TEXT PRIMARY KEY, parent_id TEXT, node_type TEXT NOT NULL, name TEXT NOT NULL,
 status TEXT NOT NULL, contract TEXT NOT NULL, evidence TEXT NOT NULL,
 created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tree_node_parent ON tree_nodes(parent_id);
CREATE TABLE IF NOT EXISTS tree_mounts (
 node_id TEXT NOT NULL, memory_id TEXT NOT NULL, relation TEXT,
 created_at TEXT NOT NULL, PRIMARY KEY(node_id, memory_id));
CREATE INDEX IF NOT EXISTS tree_mount_memory ON tree_mounts(memory_id);
CREATE TABLE IF NOT EXISTS tree_ops (
 op_id INTEGER PRIMARY KEY AUTOINCREMENT, tree_revision INTEGER NOT NULL,
 operation_type TEXT NOT NULL, status TEXT NOT NULL,
 target_refs TEXT NOT NULL, source_refs TEXT NOT NULL, previous_revision INTEGER NOT NULL,
 payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watermarks (
 source_type TEXT PRIMARY KEY, last_seq INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_groups (
 group_id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL,
 recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vector_index (
 memory_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
 dim INTEGER NOT NULL, vector BLOB NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entity_aliases (
 alias TEXT NOT NULL, entity TEXT NOT NULL, status TEXT NOT NULL, confidence REAL NOT NULL,
 evidence TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(alias, entity));
CREATE TABLE IF NOT EXISTS memory_digests (
 memory_id TEXT PRIMARY KEY, through_revision INTEGER NOT NULL, digest TEXT NOT NULL,
 created_at TEXT NOT NULL);
"""

TABLES = frozenset({"meta", "events", "identities", "memory_topics", "revisions", "heads",
                    "projection", "pending", "identity_changes", "identity_aliases",
                    "relations", "tree_nodes", "tree_mounts", "tree_ops", "watermarks",
                    "event_groups", "vector_index", "entity_aliases", "memory_digests"})

# Recognized only; the default schema never creates the opt-in entity registry.
TABLES = TABLES | frozenset({"csm_entities", "csm_entity_labels", "csm_entity_nodes",
                           "csm_entity_node_history"})
TABLES = TABLES | frozenset({"csm_property_specs", "csm_property_bindings", "csm_property_proposals",
                           "csm_property_reviews", "csm_property_commits", "csm_property_relation_events"})

ROOT_NODE = "MemorySpace"


class CsmStore:
    def __init__(self, path, *, namespace: str):
        self.path = Path(path).resolve()
        self.namespace = identifier(namespace)
        with self.connect() as db:
            db.executescript(SCHEMA)
            tables = {row[0] for row in
                      db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                 "AND name NOT LIKE 'sqlite_%'")}
            require(tables <= TABLES, "store_format_unknown")
            binding = {"schema": 1, "namespace": self.namespace}
            stored = getmeta(db, "binding")
            require(stored is None or stored == binding, "store_namespace_conflict")
            if stored is None:
                setmeta(db, "binding", binding)
            rule = getmeta(db, "identity_key_rule")
            require(rule is None or rule == IDENTITY_KEY_RULE,
                    "store_identity_key_rule_conflict")
            if rule is None:
                setmeta(db, "identity_key_rule", IDENTITY_KEY_RULE)
            if db.execute("SELECT 1 FROM tree_nodes WHERE node_id = ?",
                          (ROOT_NODE,)).fetchone() is None:
                contract = {"node_id": ROOT_NODE, "node_type": "organization",
                            "entity_anchor": None, "scope_description": "memory space root",
                            "accepted_relations": [], "context_constraints": [],
                            "evidence_refs": [], "contract_revision": 1}
                data = {"node_id": ROOT_NODE, "parent_id": None, "node_type": "organization",
                        "name": ROOT_NODE, "status": "active", "contract": contract,
                        "evidence": [], "created_at": "", "producer": "system"}
                db.execute("INSERT INTO tree_nodes(node_id, parent_id, node_type, name, status, "
                           "contract, evidence, created_at, data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (ROOT_NODE, None, "organization", ROOT_NODE, "active",
                            json.dumps(contract, sort_keys=True), "[]", "",
                            json.dumps(data, sort_keys=True, ensure_ascii=False)))
            if getmeta(db, "tree_head") is None:
                setmeta(db, "tree_head", 0)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A single writer at a time; readers never observe a half-committed state."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")


def getmeta(db: sqlite3.Connection, key: str):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else json.loads(row["value"])


def setmeta(db: sqlite3.Connection, key: str, value) -> None:
    db.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, encode(value)))
