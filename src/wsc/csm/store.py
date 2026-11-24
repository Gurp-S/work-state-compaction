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

SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 source_type TEXT NOT NULL, source_ref TEXT, observed_at TEXT,
 data TEXT NOT NULL, digest TEXT NOT NULL, metadata TEXT);
CREATE TABLE IF NOT EXISTS commits (
 commit_sha TEXT PRIMARY KEY, observed_at TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS properties (
 property_id TEXT PRIMARY KEY, entity TEXT NOT NULL, normalized_name TEXT NOT NULL,
 kind TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL,
 UNIQUE(entity, normalized_name));
CREATE TABLE IF NOT EXISTS property_aliases (
 entity TEXT NOT NULL, alias TEXT NOT NULL, property_id TEXT NOT NULL,
 PRIMARY KEY(entity, alias));
CREATE TABLE IF NOT EXISTS identities (
 memory_id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE,
 entity TEXT NOT NULL, slot TEXT NOT NULL, contexts TEXT NOT NULL,
 semantic_type TEXT NOT NULL, data TEXT NOT NULL,
 property_id TEXT, property_kind TEXT, scope TEXT);
CREATE TABLE IF NOT EXISTS memory_topics (
 memory_id TEXT NOT NULL, topic TEXT NOT NULL, PRIMARY KEY(memory_id, topic));
CREATE TABLE IF NOT EXISTS memory_symbols (
 memory_id TEXT NOT NULL, symbol TEXT NOT NULL, PRIMARY KEY(memory_id, symbol));
CREATE TABLE IF NOT EXISTS revisions (
 memory_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
 valid_from TEXT, effective_at TEXT, observed_at TEXT,
 PRIMARY KEY (memory_id, revision));
CREATE TABLE IF NOT EXISTS heads (
 memory_id TEXT PRIMARY KEY, current_revision INTEGER NOT NULL,
 projection_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS term_index (
 term TEXT NOT NULL, memory_id TEXT NOT NULL, revision INTEGER NOT NULL,
 weight INTEGER NOT NULL, PRIMARY KEY(term, memory_id, revision));
CREATE TABLE IF NOT EXISTS symbol_index (
 term TEXT NOT NULL, memory_id TEXT NOT NULL, revision INTEGER NOT NULL,
 weight INTEGER NOT NULL, PRIMARY KEY(term, memory_id, revision));
"""

SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS property_entity ON properties(entity);
CREATE INDEX IF NOT EXISTS identity_entity_slot ON identities(entity, slot);
CREATE INDEX IF NOT EXISTS identity_property ON identities(property_id);
CREATE INDEX IF NOT EXISTS topic_lookup ON memory_topics(topic);
CREATE INDEX IF NOT EXISTS symbol_lookup ON memory_symbols(symbol);
CREATE INDEX IF NOT EXISTS revision_window ON revisions(memory_id, valid_from);
CREATE INDEX IF NOT EXISTS term_lookup ON term_index(term);
CREATE INDEX IF NOT EXISTS term_memory ON term_index(memory_id, revision);
CREATE INDEX IF NOT EXISTS symbol_term_lookup ON symbol_index(term);
CREATE INDEX IF NOT EXISTS symbol_memory ON symbol_index(memory_id, revision);
"""

# A store written by the string-key model has the same tables but not the property and
# event-time columns; adding them is a schema upgrade, not a data rewrite.
COLUMN_UPGRADES = {
    "events": {"metadata": "TEXT"},
    "identities": {"property_id": "TEXT", "property_kind": "TEXT", "scope": "TEXT"},
    "revisions": {"valid_from": "TEXT", "effective_at": "TEXT", "observed_at": "TEXT"},
}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def upgrade_columns(db: sqlite3.Connection) -> None:
    for table, wanted in COLUMN_UPGRADES.items():
        present = _columns(db, table)
        for name, declaration in wanted.items():
            if name not in present:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    # The term index is derived. A pre-revision index cannot answer as-of search, so it is
    # replaced here and rebuilt by ``CSM.rebuild``; no source or memory data is touched.
    if "revision" not in _columns(db, "term_index"):
        db.execute("DROP TABLE term_index")
        db.execute("CREATE TABLE term_index (term TEXT NOT NULL, memory_id TEXT NOT NULL, "
                   "revision INTEGER NOT NULL, weight INTEGER NOT NULL, "
                   "PRIMARY KEY(term, memory_id, revision))")

# Legacy names are recognized so an old store can still be opened and read, but the new
# schema never creates them and the core never imports their mechanisms.
TABLES = frozenset({
    "meta", "events", "commits", "properties", "property_aliases", "identities",
    "memory_topics", "memory_symbols", "revisions", "heads", "projection", "term_index",
    "symbol_index",
    "pending", "identity_changes", "identity_aliases", "relations", "tree_nodes", "tree_mounts",
    "tree_ops", "watermarks", "event_groups", "vector_index", "entity_aliases", "memory_digests",
    "csm_entities", "csm_entity_labels", "csm_entity_nodes", "csm_entity_node_history",
    "csm_property_specs", "csm_property_bindings", "csm_property_proposals",
    "csm_property_reviews", "csm_property_commits", "csm_property_relation_events",
})

SCHEMA_VERSION = 4


class CsmStore:
    def __init__(self, path, *, namespace: str):
        self.path = Path(path).resolve()
        self.namespace = identifier(namespace)
        with self.connect() as db:
            db.executescript(SCHEMA_TABLES)
            upgrade_columns(db)
            db.executescript(SCHEMA_INDEXES)
            try:
                db.execute("PRAGMA journal_mode = WAL")
                db.execute("PRAGMA synchronous = NORMAL")
            except sqlite3.DatabaseError:
                pass
            tables = {row[0] for row in
                      db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                 "AND name NOT LIKE 'sqlite_%'")}
            require(tables <= TABLES, "store_format_unknown")
            stored = getmeta(db, "binding")
            if stored is None:
                setmeta(db, "binding", {"schema": SCHEMA_VERSION, "namespace": self.namespace})
            else:
                require(stored.get("namespace") == self.namespace, "store_namespace_conflict")
            if getmeta(db, "identity_key_rule") is None:
                setmeta(db, "identity_key_rule", IDENTITY_KEY_RULE)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA busy_timeout = 30000")
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
