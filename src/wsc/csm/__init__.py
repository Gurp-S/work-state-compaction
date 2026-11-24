"""CSM: stateful semantic memory over an event log, not a compression layer.

Core: event evidence, engine-owned properties, versioned state, event-scoped observations,
term-indexed retrieval with source excerpts, as-of selection by event time, consolidation.
"""
from .contracts import (CSMError, Event, MemoryCandidate, MemoryQuery, TYPE_TREE,
                        CURRENT_CONFIRMED, HISTORICAL, UNKNOWN)
from .scope import branch_scope, chain, repo_scope
from .service import CSM
from .store import CsmStore

__all__ = ["CSM", "CsmStore", "CSMError", "Event", "MemoryCandidate", "MemoryQuery",
           "TYPE_TREE", "CURRENT_CONFIRMED", "HISTORICAL", "UNKNOWN",
           "repo_scope", "branch_scope", "chain"]
