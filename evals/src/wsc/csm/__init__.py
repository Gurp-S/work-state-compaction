"""CSM: stateful semantic memory over an event log, not a compression layer.

Minimal P0 slice: event evidence, memory identity, versioned state, identity
pending, current-state projection, deterministic retrieval, rebuild.
"""
from .contracts import (CSMError, Event, MemoryCandidate, MemoryQuery, TYPE_TREE,
                        CURRENT_CONFIRMED, HISTORICAL, PENDING_BINDING, UNKNOWN)
from .service import CSM
from .store import CsmStore

__all__ = ["CSM", "CsmStore", "CSMError", "Event", "MemoryCandidate", "MemoryQuery",
           "TYPE_TREE", "CURRENT_CONFIRMED", "HISTORICAL", "PENDING_BINDING", "UNKNOWN"]
