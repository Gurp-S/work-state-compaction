"""Incremental event integrity: append-only hash chain plus a verified cursor.

The chain links every event row's recorded digest to its predecessor, so a
rewritten, reordered, or truncated history is detectable.  Two cursors keep the
cost proportional to *new* rows rather than to the whole history:
``chained_through`` (how far the chain has been extended) and
``verified_through`` (how far the text has been re-hashed and checked).

Receipts use the same two layers.  Routine ingest runs an incremental check that
covers only new receipts; an explicit full audit re-hashes the whole history and
is the only check that can detect a rewrite of an already-verified receipt.
Both return an assurance record (``scope``, ``verified_through``,
``full_verified_through``, ``last_full_audit_at``, ``integrity_root``) so a
partial check can never be reported as a complete one.

Nothing here is enabled implicitly: callers opt in with ``policy='chain_v1'``
and the tables are created on first use.  Existing tables are never dropped or
rewritten; the verify cursor gains its audit columns additively.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .contracts import require

POLICY = "chain_v1"
# Bump when the receipt link recipe or the receipt payload changes: a full-audit
# checkpoint recorded under another version must never be reused.
RECEIPT_INTEGRITY_VERSION = 1
GENESIS = "0" * 64

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_event_chain_v1(
        seq INTEGER PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        digest TEXT NOT NULL,
        link TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_integrity_state_v1(
        name TEXT PRIMARY KEY,
        chained_through INTEGER NOT NULL,
        verified_through INTEGER NOT NULL,
        head TEXT NOT NULL
    )""",
)


def installed(db) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wsc_event_chain_v1'"
                      ).fetchone() is not None


def install(db) -> None:
    # Individual statements, not executescript: executescript commits the open
    # transaction, which would break the single-transaction ingest guarantee.
    for statement in _SCHEMA:
        db.execute(statement)


def _ensure(db) -> None:
    if not installed(db):
        install(db)


def link(prev: str, seq: int, event_id: str, digest: str) -> str:
    return sha256(f"{prev}\n{seq}\n{event_id}\n{digest}".encode("utf-8")).hexdigest()


def _state(db) -> tuple[int, int, str]:
    row = db.execute("SELECT chained_through, verified_through, head FROM wsc_integrity_state_v1 "
                     "WHERE name='events'").fetchone()
    return (0, 0, GENESIS) if row is None else (int(row[0]), int(row[1]), row[2])


def _save(db, chained: int, verified: int, head: str) -> None:
    db.execute("INSERT INTO wsc_integrity_state_v1(name, chained_through, verified_through, head) "
               "VALUES ('events',?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "chained_through=excluded.chained_through, "
               "verified_through=excluded.verified_through, head=excluded.head",
               (chained, verified, head))


def advance(db) -> dict:
    """Link event rows newer than the chained cursor. Idempotent; O(new rows)."""
    _ensure(db)
    chained, verified, head = _state(db)
    scanned = hashed = 0
    for seq, event_id, digest in db.execute(
            "SELECT seq, id, digest FROM events WHERE seq>? ORDER BY seq", (chained,)).fetchall():
        head = link(head, seq, event_id, digest)
        existing = db.execute("SELECT event_id, digest, link FROM wsc_event_chain_v1 WHERE seq=?",
                              (seq,)).fetchone()
        if existing is None:
            db.execute("INSERT INTO wsc_event_chain_v1(seq, event_id, digest, link) VALUES (?,?,?,?)",
                       (seq, event_id, digest, head))
        elif tuple(existing) != (event_id, digest, head):
            # Same position, different content: a committed link is history, so
            # replacing it would hide the rewrite the chain exists to expose.
            require(False, "integrity_chain_conflict")
        chained = seq
        scanned += 1
        hashed += len(digest)
    if scanned:
        _save(db, chained, verified, head)
    return {"scanned": scanned, "hashed": hashed, "through": chained}


def verify(db, *, full: bool = False) -> dict:
    """Re-hash chained events beyond the verified cursor and check the links.

    Raises ``source_integrity_mismatch`` when stored text no longer matches its
    recorded digest, and ``integrity_chain_broken`` when a chain row is missing,
    reordered, or relinked.
    """
    _ensure(db)
    chained, verified, head = _state(db)
    if full:
        verified, prev = 0, GENESIS
    elif verified:
        row = db.execute("SELECT link FROM wsc_event_chain_v1 WHERE seq=?", (verified,)).fetchone()
        require(row is not None, "integrity_chain_broken")
        prev = row[0]
    else:
        prev = GENESIS
    scanned = hashed = 0
    expected = verified + 1
    last = verified
    for seq, event_id, digest, data, recorded in db.execute(
            "SELECT c.seq, c.event_id, c.digest, e.data, c.link FROM wsc_event_chain_v1 c "
            "LEFT JOIN events e ON e.seq=c.seq WHERE c.seq>? ORDER BY c.seq", (verified,)).fetchall():
        require(seq == expected, "integrity_chain_broken")
        # A LEFT JOIN keeps a chain row whose event row is gone visible; an inner
        # join would drop it and report a history with a hole as intact.
        require(data is not None, "source_integrity_mismatch")
        require(sha256(data.encode("utf-8")).hexdigest() == digest, "source_integrity_mismatch")
        require(link(prev, seq, event_id, digest) == recorded, "integrity_chain_broken")
        prev, last, expected = recorded, seq, seq + 1
        scanned += 1
        hashed += len(data)
    if scanned:
        _save(db, chained, last, head)
    return {"scanned": scanned, "hashed": hashed, "through": last, "ok": True}


_RECEIPT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_receipt_chain_v1(
        rowid_ INTEGER PRIMARY KEY,
        receipt_id TEXT NOT NULL UNIQUE,
        source_ids TEXT NOT NULL,
        link TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_receipt_state_v1(
        name TEXT PRIMARY KEY,
        chained_through INTEGER NOT NULL,
        head TEXT NOT NULL
    )""",
)

# Additive tables: the source index answers "was this id presented?" in O(1),
# and the verify cursor keeps a receipt check proportional to new receipts.
# The same cursor row records the last successful full audit, so callers can
# tell a routine incremental check from an assurance over the whole history.
_RECEIPT_AUX_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wsc_receipt_sources_v1(
        source_id TEXT NOT NULL,
        receipt_id TEXT NOT NULL,
        PRIMARY KEY(source_id, receipt_id)
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_receipt_verified_v1(
        name TEXT PRIMARY KEY,
        verified_rowid INTEGER NOT NULL,
        verified_link TEXT NOT NULL,
        full_verified_through INTEGER NOT NULL DEFAULT 0,
        last_full_audit_at TEXT,
        integrity_root TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS wsc_receipt_aux_v1(
        version INTEGER PRIMARY KEY,
        installed_at TEXT NOT NULL,
        indexed_through INTEGER NOT NULL DEFAULT -1
    )""",
)

# Bump when a derived table gains a column or changes its key: a database whose
# marker carries an older version is migrated once instead of being trusted.
# 2: the marker records how far the source index reaches (``indexed_through``).
AUX_VERSION = 2

# Columns added after the first release of the verify cursor: migrate in place
# instead of dropping the cursor (a drop would silently replay verification).
_AUDIT_COLUMNS = (
    ("full_verified_through", "INTEGER NOT NULL DEFAULT 0"),
    ("last_full_audit_at", "TEXT"),
    ("integrity_root", "TEXT"),
)

# A committed receipt is history: the normal path may append, never rewrite or
# remove.  Enforced in the database so no code path (or future one) can skip it.
_RECEIPT_GUARDS = (
    """CREATE TRIGGER IF NOT EXISTS wsc_receipts_append_only_update
       BEFORE UPDATE ON presentations BEGIN
         SELECT RAISE(ABORT, 'receipt_immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS wsc_receipts_append_only_delete
       BEFORE DELETE ON presentations BEGIN
         SELECT RAISE(ABORT, 'receipt_immutable'); END""",
)

# The chain is derived, but a committed chain row is also history: rewriting a
# link or swapping its receipt_id would make a full audit disagree with itself
# depending on which column it trusted.  Same append-only contract as receipts.
_CHAIN_GUARDS = (
    """CREATE TRIGGER IF NOT EXISTS wsc_receipt_chain_append_only_update
       BEFORE UPDATE ON wsc_receipt_chain_v1 BEGIN
         SELECT RAISE(ABORT, 'receipt_chain_immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS wsc_receipt_chain_append_only_delete
       BEFORE DELETE ON wsc_receipt_chain_v1 BEGIN
         SELECT RAISE(ABORT, 'receipt_chain_immutable'); END""",
)


def receipts_installed(db) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wsc_receipt_chain_v1'"
                      ).fetchone() is not None


def install_receipts(db) -> None:
    for statement in _RECEIPT_SCHEMA:
        db.execute(statement)


_HEX_DIGITS = frozenset("0123456789abcdef")


def _stored_int(value, *, code: str, minimum: int = 0) -> int:
    """An INTEGER column's value, refusing anything SQLite had to coerce.

    ``int()`` reads a REAL such as ``1.5`` as ``1`` and the TEXT ``"1"`` as ``1``,
    which turns a corrupt persisted state into a legal checkpoint.  SQLite hands
    back a Python ``int`` only for a stored INTEGER, so any other type is a state
    this release never writes and is refused rather than normalised.
    """
    require(type(value) is int and value >= minimum, code)
    return value


def _stored_head(value, *, code: str) -> str:
    """A chain head: 64 lowercase hex digits, nothing else."""
    require(isinstance(value, str) and len(value) == 64 and set(value) <= _HEX_DIGITS, code)
    return value


def _receipt_state(db) -> tuple[int, str]:
    row = db.execute("SELECT chained_through, head FROM wsc_receipt_state_v1 WHERE name='receipts'").fetchone()
    if row is None:
        return (0, GENESIS)
    return (_stored_int(row[0], code="receipt_state_invalid"),
            _stored_head(row[1], code="receipt_state_invalid"))


def receipt_state(db) -> tuple[int, str]:
    """(chained_through, head) for receipts; GENESIS when the chain is empty."""
    return _receipt_state(db)


# ``receipt_count`` is the number of chained receipts, maintained in the same
# transaction as the append.  ``-1`` means "not backfilled yet" (databases
# created before the column existed): a reader must then fall back to a full
# audit once, which repairs the row, instead of trusting a COUNT every release.
_UNKNOWN_COUNT = -1


def receipt_status(db) -> tuple[int, int, str] | None:
    """(count, chained_through, head), or None when no state row exists yet."""
    row = db.execute("SELECT receipt_count, chained_through, head FROM wsc_receipt_state_v1 "
                     "WHERE name='receipts'").fetchone()
    if row is None:
        return None
    return (_stored_int(row[0], code="receipt_count_invalid", minimum=_UNKNOWN_COUNT),
            _stored_int(row[1], code="receipt_state_invalid"),
            _stored_head(row[2], code="receipt_state_invalid"))


def _save_receipts(db, chained: int, head: str, count: int) -> None:
    db.execute("INSERT INTO wsc_receipt_state_v1(name, chained_through, head, receipt_count) "
               "VALUES ('receipts',?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "chained_through=excluded.chained_through, head=excluded.head, "
               "receipt_count=excluded.receipt_count", (chained, head, count))


def record_receipt_count(db, count: int) -> None:
    """Backfill the persisted receipt count after a successful full audit."""
    require(type(count) is int and count >= 0, "receipt_count_invalid")
    chained, head = _receipt_state(db)
    _save_receipts(db, chained, head, count)


def _chain_cursor(db) -> int:
    """How far the receipt chain is linked; 0 before the first receipt."""
    status = receipt_status(db)
    return 0 if status is None else status[1]


def _index_coverage(db) -> int:
    """The chain position the source index was last known to cover; -1 if none."""
    row = db.execute("SELECT indexed_through FROM wsc_receipt_aux_v1 WHERE version=?",
                     (AUX_VERSION,)).fetchone()
    if row is None:
        return -1
    return _stored_int(row[0], code="receipt_state_invalid", minimum=-1)


def _save_index_coverage(db, chained: int) -> None:
    require(type(chained) is int and chained >= 0, "receipt_state_invalid")
    db.execute("INSERT INTO wsc_receipt_aux_v1(version, installed_at, indexed_through) "
               "VALUES (?,?,?) ON CONFLICT(version) DO UPDATE SET "
               "installed_at=excluded.installed_at, indexed_through=excluded.indexed_through",
               (AUX_VERSION, _now(), chained))


def _aux_current(db) -> bool:
    """Whether the derived schema is already at ``AUX_VERSION`` and present.

    ``is_delivered`` runs once per source, and re-declaring the derived tables
    and their guards on every call cost more than the lookup it protects
    (benchmarks/receipt_index_ab.py measures the split).  Two catalogue lookups
    replace the DDL batch; a missing table still forces the full path, so a
    dropped index is rebuilt rather than trusted.
    """
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('wsc_receipt_sources_v1','wsc_receipt_aux_v1')").fetchall()}
    if tables != {"wsc_receipt_sources_v1", "wsc_receipt_aux_v1"}:
        return False
    return db.execute("SELECT 1 FROM wsc_receipt_aux_v1 WHERE version=?",
                      (AUX_VERSION,)).fetchone() is not None


def _index_key(db) -> list[str]:
    """The index's primary-key columns, in declaration order."""
    return [row[1] for row in db.execute("PRAGMA table_info(wsc_receipt_sources_v1)").fetchall()
            if row[5]]


def _rebuild_index(db) -> None:
    """Recreate the source index from the authoritative receipts, in place.

    Two things force a rebuild: the index is missing, or it was created by a
    release that keyed it by ``source_id`` alone.  That older key kept only one
    receipt per source, so a source presented twice lost a receipt and the
    table could never be reconciled with the history.  The rows are re-derived
    from ``presentations.data`` - the authoritative receipt - so a corrupted
    index cannot seed its own replacement.
    """
    db.execute("DROP TABLE IF EXISTS wsc_receipt_sources_v1_next")
    db.execute("CREATE TABLE wsc_receipt_sources_v1_next(source_id TEXT NOT NULL, "
               "receipt_id TEXT NOT NULL, PRIMARY KEY(source_id, receipt_id))")
    db.executemany("INSERT OR IGNORE INTO wsc_receipt_sources_v1_next VALUES (?,?)",
                   [(source_id, receipt_id)
                    for receipt_id, data in db.execute(
                        "SELECT id, data FROM presentations ORDER BY rowid").fetchall()
                    for source_id in json.loads(data)["source_ids"]])
    db.execute("DROP TABLE wsc_receipt_sources_v1")
    db.execute("ALTER TABLE wsc_receipt_sources_v1_next RENAME TO wsc_receipt_sources_v1")


def _ensure_receipt_aux(db) -> None:
    """Create the derived tables, migrate in place and backfill once.

    The backfill reads ``presentations.data`` - the authoritative receipt - not
    the chain's ``source_ids`` copy, so a corrupted derived column cannot seed
    the index it is supposed to be rebuilt from.
    """
    if _aux_current(db):
        return
    created = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                         "AND name='wsc_receipt_sources_v1'").fetchone() is None
    for statement in _RECEIPT_AUX_SCHEMA:
        db.execute(statement)
    for statement in _RECEIPT_GUARDS + _CHAIN_GUARDS:
        db.execute(statement)
    columns = {row[1] for row in db.execute("PRAGMA table_info(wsc_receipt_verified_v1)").fetchall()}
    for name, declaration in _AUDIT_COLUMNS:
        if name not in columns:
            db.execute(f"ALTER TABLE wsc_receipt_verified_v1 ADD COLUMN {name} {declaration}")
    state_columns = {row[1] for row in db.execute("PRAGMA table_info(wsc_receipt_state_v1)").fetchall()}
    if "receipt_count" not in state_columns:
        db.execute(f"ALTER TABLE wsc_receipt_state_v1 ADD COLUMN receipt_count INTEGER "
                   f"NOT NULL DEFAULT {_UNKNOWN_COUNT}")
    aux_columns = {row[1] for row in db.execute("PRAGMA table_info(wsc_receipt_aux_v1)").fetchall()}
    if "indexed_through" not in aux_columns:
        db.execute("ALTER TABLE wsc_receipt_aux_v1 ADD COLUMN indexed_through INTEGER "
                   "NOT NULL DEFAULT -1")
    if created or _index_key(db) != ["source_id", "receipt_id"]:
        _rebuild_index(db)
        _save_index_coverage(db, _chain_cursor(db))
    elif _index_coverage(db) < 0:
        # A marker from the release before coverage was tracked: the index was
        # built from every receipt present, so it covers the chain as linked.
        _save_index_coverage(db, _chain_cursor(db))


def _restore_receipt_state(db) -> tuple[int, str, int]:
    """Rebuild the chain cursor after the state row was lost.

    A missing state row is not an empty history: the chain may already carry
    every receipt, so starting from GENESIS would walk that history again and
    count it a second time.  The cursor is rebuilt only after the existing chain
    has been verified end to end against the authoritative receipts - position,
    receipt id, sources and link - and is refused outright when the chain cannot
    prove the history it claims.

    Both directions are proved before anything is written.  Walking the receipts
    shows every receipt has its chain row; it does not show that every chain row
    has a receipt, and a row nothing vouches for can sit anywhere - below the
    last verified rowid as easily as above it.  Such a row is not history, so the
    repair refuses instead of restoring a cursor over a chain that disagrees with
    the receipts.
    """
    head, chained, count = GENESIS, 0, 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations ORDER BY rowid").fetchall():
        row = db.execute("SELECT receipt_id, source_ids, link FROM wsc_receipt_chain_v1 "
                         "WHERE rowid_=?", (rowid,)).fetchone()
        if row is None:
            break  # receipts newer than the chain are linked by the caller
        expected = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        require(tuple(row) == (receipt_id, " ".join(json.loads(data)["source_ids"]), expected),
                "receipt_state_unrecoverable")
        head, chained, count = expected, rowid, count + 1
    # The other direction: every chain row must name a receipt that exists.  A
    # membership test, not a count or a rowid comparison - an orphan can carry a
    # rowid below the cursor and still leave the totals looking right.
    require(db.execute(
        "SELECT 1 FROM wsc_receipt_chain_v1 AS c WHERE NOT EXISTS "
        "(SELECT 1 FROM presentations AS p WHERE p.rowid = c.rowid_) LIMIT 1"
    ).fetchone() is None, "receipt_state_unrecoverable")
    # And the chain must be a prefix of the receipts: a chain row past the last
    # receipt - or past a hole in the chain - is a link nothing can vouch for,
    # and rewriting it is not an option.
    require(db.execute("SELECT 1 FROM wsc_receipt_chain_v1 WHERE rowid_>? LIMIT 1",
                       (chained,)).fetchone() is None, "receipt_state_unrecoverable")
    _save_receipts(db, chained, head, count)
    # The chain vouches for the receipts, not for the derived index.  Restoring
    # the cursor would make an index with a missing row look complete, and a
    # missing row reads as "this source was never presented", so the index is
    # re-derived from the receipts this pass just verified.  Coverage is claimed
    # only after that rebuild, never before it.
    _ensure_receipt_aux(db)
    _rebuild_index(db)
    _save_index_coverage(db, chained)
    return chained, head, count


def ensure_receipt_state(db) -> tuple[int, int, str]:
    """(count, chained_through, head), rebuilding a lost state row first.

    A missing state row is not an empty history: the chain may already carry
    every receipt.  A reader that started from GENESIS would walk that history
    again, and a full audit would compare its result against the wrong head and
    fail a database that is recoverable.  ``_restore_receipt_state`` verifies the
    chain against the authoritative receipts in both directions and refuses when
    it cannot, so the repair never invents a cursor.  A database with no receipts
    at all gets the same GENESIS row ``advance_receipts`` writes.
    """
    status = receipt_status(db)
    if status is not None:
        return status
    chained, head, count = _restore_receipt_state(db)
    return count, chained, head


def advance_receipts(db) -> dict:
    """Link presentation receipts newer than the cursor. Idempotent; O(new receipts).

    ``scanned`` counts every receipt this pass walked; ``inserted`` counts the
    ones that were not chained yet.  Only ``inserted`` grows the persisted count,
    so re-walking a history - which happens whenever the state row is rebuilt -
    cannot count it twice.
    """
    if not receipts_installed(db):
        install_receipts(db)
    _ensure_receipt_aux(db)
    status = receipt_status(db)
    backfilled = False
    if status is None:
        chained, head, count = _restore_receipt_state(db)
        # Every row the rebuild walked was verified against its receipt, so it
        # is reported as scanned - and counted as neither inserted nor new.
        scanned = count
    else:
        count, chained, head = status
        if count < 0:
            # One-time backfill for databases created before the column existed.
            count = _stored_int(db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0],
                                code="receipt_count_invalid")
            backfilled = True
        scanned = 0
    start = chained
    inserted = 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations WHERE rowid>? ORDER BY rowid", (chained,)).fetchall():
        link_value = link(head, rowid, receipt_id, sha256(data.encode("utf-8")).hexdigest())
        source_ids = " ".join(json.loads(data)["source_ids"])
        existing = db.execute("SELECT receipt_id, source_ids, link FROM wsc_receipt_chain_v1 "
                              "WHERE rowid_=?", (rowid,)).fetchone()
        if existing is None:
            db.execute("INSERT INTO wsc_receipt_chain_v1(rowid_, receipt_id, source_ids, link) "
                       "VALUES (?,?,?,?)", (rowid, receipt_id, source_ids, link_value))
            inserted += 1
        elif tuple(existing) != (receipt_id, source_ids, link_value):
            # Same position, different content: the chain and the receipt
            # disagree.  Replacing the row would hide that, so refuse.
            require(False, "receipt_chain_conflict")
        for source_id in source_ids.split():
            db.execute("INSERT OR IGNORE INTO wsc_receipt_sources_v1 VALUES (?,?)",
                       (source_id, receipt_id))
        head = link_value
        chained = rowid
        scanned += 1
    if scanned or backfilled or chained != start:
        _save_receipts(db, chained, head, count + inserted)
        _save_index_coverage(db, chained)
    return {"scanned": scanned, "inserted": inserted, "through": chained, "head": head,
            "count": count + inserted}


def _receipt_verified(db) -> tuple[int, str]:
    row = db.execute("SELECT verified_rowid, verified_link FROM wsc_receipt_verified_v1 "
                     "WHERE name='receipts'").fetchone()
    if row is None:
        return (0, GENESIS)
    return (_stored_int(row[0], code="receipt_state_invalid"),
            _stored_head(row[1], code="receipt_state_invalid"))


def _save_receipt_verified(db, rowid: int, head: str) -> None:
    db.execute("INSERT INTO wsc_receipt_verified_v1(name, verified_rowid, verified_link) "
               "VALUES ('receipts',?,?) ON CONFLICT(name) DO UPDATE SET "
               "verified_rowid=excluded.verified_rowid, verified_link=excluded.verified_link",
               (rowid, head))


def _receipt_audit(db) -> tuple[int, str | None]:
    row = db.execute("SELECT full_verified_through, last_full_audit_at FROM wsc_receipt_verified_v1 "
                     "WHERE name='receipts'").fetchone()
    if row is None:
        return (0, None)
    at = row[1]
    require(at is None or isinstance(at, str), "receipt_state_invalid")
    return (_stored_int(row[0], code="receipt_state_invalid"), at)


def _save_audit(db, through: int, at: str, root: str) -> None:
    db.execute("INSERT INTO wsc_receipt_verified_v1(name, verified_rowid, verified_link, "
               "full_verified_through, last_full_audit_at, integrity_root) "
               "VALUES ('receipts',?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "verified_rowid=excluded.verified_rowid, verified_link=excluded.verified_link, "
               "full_verified_through=excluded.full_verified_through, "
               "last_full_audit_at=excluded.last_full_audit_at, "
               "integrity_root=excluded.integrity_root",
               (through, root, through, at, root))


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _receipt_result(*, ok: bool, scope: str, count: int, scanned: int, verified_through: int,
                    full_verified_through: int, last_full_audit_at: str | None,
                    integrity_root: str, head: str, hashed: int = 0) -> dict:
    """One shape for every outcome, so a partial check is never read as a full one."""
    return {"ok": ok, "scope": scope, "count": count, "scanned": scanned, "hashed": hashed,
            "verified_through": verified_through,
            "full_verified_through": full_verified_through,
            "last_full_audit_at": last_full_audit_at,
            "integrity_root": integrity_root, "head": head}


def _receipt_count(db) -> int:
    """Total chained receipts, from the persisted counter when it is known.

    The counter is O(1); a database that predates it (``-1``) pays one COUNT,
    which the next successful full audit repairs.
    """
    status = receipt_status(db)
    if status is not None and status[0] >= 0:
        return status[0]
    return _stored_int(db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0],
                       code="receipt_count_invalid")


def verify_receipts(db, *, full: bool = False) -> dict:
    """Check receipts against the chain, re-hashing only receipts past the cursor.

    ``scope`` says what this run actually covered. ``incremental`` re-hashes new
    receipts and rejects a chain that ends early (truncation); it cannot see a
    rewrite of a receipt that was already verified, because that adds no row.
    ``full`` recomputes the whole chain and is the only scope that detects such a
    rewrite, so a release must not treat an incremental result as assurance over
    the whole history. Every outcome carries ``verified_through``,
    ``full_verified_through``, ``last_full_audit_at`` and ``integrity_root`` so a
    caller cannot mistake a partial check for a complete one.

    ``count`` is the size of the receipt history, not the work this run did:
    ``scanned`` reports that separately.  Reporting the scan as the count made an
    incremental check look like a one-receipt history.
    """
    scope = "full" if full else "incremental"
    if not receipts_installed(db):
        return _receipt_result(ok=True, scope=scope, count=0, scanned=0, verified_through=0,
                               full_verified_through=0, last_full_audit_at=None,
                               integrity_root=GENESIS, head=GENESIS)
    _ensure_receipt_aux(db)
    _, _, recorded = ensure_receipt_state(db)
    full_through, last_audit = _receipt_audit(db)
    verified, verified_link = _receipt_verified(db)
    total = _receipt_count(db)
    chain_max = db.execute("SELECT COALESCE(MAX(rowid_),0) FROM wsc_receipt_chain_v1").fetchone()[0]
    rows_max = db.execute("SELECT COALESCE(MAX(rowid),0) FROM presentations").fetchone()[0]
    if chain_max != rows_max:
        return _receipt_result(ok=False, scope=scope, count=total, scanned=0, verified_through=verified,
                               full_verified_through=full_through, last_full_audit_at=last_audit,
                               integrity_root=recorded, head=recorded)
    if full:
        chain_count = db.execute("SELECT COUNT(*) FROM wsc_receipt_chain_v1").fetchone()[0]
        rows_count = db.execute("SELECT COUNT(*) FROM presentations").fetchone()[0]
        if chain_count != rows_count:
            return _receipt_result(ok=False, scope=scope, count=total, scanned=0,
                                   verified_through=verified, full_verified_through=full_through,
                                   last_full_audit_at=last_audit, integrity_root=recorded, head=recorded)
        start, prev = 0, GENESIS
    else:
        start, prev = verified, verified_link
        if start:
            row = db.execute("SELECT link FROM wsc_receipt_chain_v1 WHERE rowid_=?", (start,)).fetchone()
            if row is None or row[0] != prev:
                return _receipt_result(ok=False, scope=scope, count=total, scanned=0,
                                       verified_through=verified, full_verified_through=full_through,
                                       last_full_audit_at=last_audit, integrity_root=recorded, head=recorded)
    head, last, scanned, hashed = prev, start, 0, 0
    for rowid, receipt_id, data in db.execute(
            "SELECT rowid, id, data FROM presentations WHERE rowid>? ORDER BY rowid", (start,)).fetchall():
        digest = sha256(data.encode("utf-8")).hexdigest()
        expected = link(head, rowid, receipt_id, digest)
        row = db.execute("SELECT receipt_id, source_ids, link FROM wsc_receipt_chain_v1 "
                         "WHERE rowid_=?", (rowid,)).fetchone()
        # The chain is derived: every column it carries must agree with the
        # authoritative receipt, not just the link.  A tampered receipt_id or
        # source_ids keeps the link valid only if the attacker also rewrites the
        # link, which the head check below then rejects - so all three are
        # compared against the receipt itself.
        if row is None or row[2] != expected:
            return _receipt_result(ok=False, scope=scope, count=total, scanned=scanned,
                                   verified_through=last, full_verified_through=full_through,
                                   last_full_audit_at=last_audit, integrity_root=recorded, head=head,
                                   hashed=hashed)
        if row[0] != receipt_id or row[1] != " ".join(json.loads(data)["source_ids"]):
            return _receipt_result(ok=False, scope=scope, count=total, scanned=scanned,
                                   verified_through=last, full_verified_through=full_through,
                                   last_full_audit_at=last_audit, integrity_root=recorded, head=head,
                                   hashed=hashed)
        head, last = expected, rowid
        scanned += 1
        hashed += len(data)
    ok = head == recorded
    if full:
        if ok:
            at = _now()
            _save_audit(db, last, at, recorded)
            full_through, last_audit = last, at
            total = chain_count
            # A verified full pass is the only scope that can state the history:
            # it walked every receipt and ended on the recorded head, so the
            # cursor it produced is the authoritative one.  Any disagreement
            # with the persisted row - the legacy -1, a wrong positive count, a
            # position the audit just proved wrong - is repaired here, in the
            # transaction that proved it, rather than by every later reader.
            _save_receipts(db, last, recorded, chain_count)
        verified_through = last if ok else verified
    else:
        if scanned:
            _save_receipt_verified(db, last, head)
        verified_through = last if scanned else verified
    return _receipt_result(ok=ok, scope=scope, count=total, scanned=scanned,
                           verified_through=verified_through, full_verified_through=full_through,
                           last_full_audit_at=last_audit, integrity_root=recorded, head=head,
                           hashed=hashed)


def audit_receipts(db) -> dict:
    """Explicit full audit: re-hash the entire receipt history. O(history)."""
    return verify_receipts(db, full=True)


def rebuild_receipt_index(db) -> dict:
    """Recreate the derived source index from the authoritative receipts.

    A rebuild trusts nothing in the chain: the whole history is audited first,
    sources are re-extracted from ``presentations.data``, and the rebuilt index
    is checked against those receipts again.  Any failure raises, so the
    caller's transaction rolls back and the previous index survives intact.
    """
    _ensure_receipt_aux(db)
    report = verify_receipts(db, full=True)
    require(report["ok"], "receipt_audit_failed")
    derived = [(source_id, receipt_id)
               for receipt_id, data in db.execute(
                   "SELECT id, data FROM presentations ORDER BY rowid").fetchall()
               for source_id in json.loads(data)["source_ids"]]
    db.execute("DELETE FROM wsc_receipt_sources_v1")
    db.executemany("INSERT OR IGNORE INTO wsc_receipt_sources_v1 VALUES (?,?)", derived)
    stored = {(row[0], row[1]) for row in
              db.execute("SELECT source_id, receipt_id FROM wsc_receipt_sources_v1")}
    require(stored == set(derived), "receipt_index_mismatch")
    _save_index_coverage(db, _chain_cursor(db))
    return {"rebuilt": len(derived), "receipts": report["count"], "head": report["head"]}


def delivered(db) -> set[str]:
    """All presented source ids, derived from the authoritative receipts."""
    if not receipts_installed(db):
        return set()
    require(verify_receipts(db)["ok"], "presentation_receipt_integrity")
    ids: set[str] = set()
    for (data,) in db.execute("SELECT data FROM presentations").fetchall():
        ids.update(json.loads(data)["source_ids"])
    return ids


def is_delivered(db, source_id: str, *, verified: bool = False) -> bool:
    """Whether one source was presented; ``verified`` skips the receipt check.

    The source index is a lookup accelerator only: a hit is confirmed against
    the receipt it points at, so a stale or tampered index can never by itself
    turn an unpresented source into a delivered one.  One JOIN fetches the
    candidate receipts lazily, so a hit costs the same regardless of how many
    receipts mention the source.

    A miss is only meaningful if the index covers the whole chain.  When it does
    not - dropped table, an index left behind by an older release, a receipt
    chained without its index rows, a lost state row - the derived table is
    rebuilt once from the authoritative receipts, so an absent row is never
    reported as "never presented" while the index is known to be incomplete.  A
    row deleted from a current index is not detectable here;
    ``rebuild_receipt_index`` audits and reconciles that case.
    """
    if not receipts_installed(db):
        return False
    if not verified:
        require(verify_receipts(db)["ok"], "presentation_receipt_integrity")
    _ensure_receipt_aux(db)
    if _confirmed(db, source_id):
        return True
    status = receipt_status(db)
    if status is None:
        # A lost state row would read as "nothing chained" below and record the
        # index as covering nothing.  The restore re-derives both from the
        # receipts it verified, so its result is the answer for this source.
        ensure_receipt_state(db)
        return _confirmed(db, source_id)
    chained = status[1]
    if _index_coverage(db) == chained:
        return False
    _rebuild_index(db)
    _save_index_coverage(db, chained)
    return _confirmed(db, source_id)


def _confirmed(db, source_id: str) -> bool:
    """Whether a receipt in the index really lists ``source_id``.

    The rows are read lazily: a real hit is confirmed by the first receipt and
    stops there, and only an index that contradicts every candidate (a forged
    row) has to walk them all.
    """
    for (data,) in db.execute("SELECT p.data FROM wsc_receipt_sources_v1 s "
                              "JOIN presentations p ON p.id=s.receipt_id WHERE s.source_id=?",
                              (source_id,)):
        if source_id in json.loads(data)["source_ids"]:
            return True
    return False
