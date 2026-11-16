"""WSC -> CSM event bridge (§14.2): WSC owns the event source, CSM owns the state.

The bridge maps an already-recorded WSC event onto a CSM ``Event`` without reinterpreting
it: the id stays stable under a ``wsc:`` prefix so re-ingesting is idempotent, the payload
is copied as-is, and no CSM decision happens here. Classification stays with the caller.
"""
from __future__ import annotations

from .contracts import Event, require


def from_wsc_event(event: dict) -> Event:
    """One WSC event as a CSM event; a missing id is a contract error, not a guess."""
    require(isinstance(event, dict), "wsc_event_invalid")
    event_id = event.get("id") or event.get("event_id")
    require(isinstance(event_id, str) and bool(event_id.strip()), "wsc_event_id_missing")
    source_type = event.get("source_type") or event.get("type") or event.get("kind") or "wsc"
    observed = event.get("observed_at") or event.get("ts") or event.get("timestamp")
    payload = event.get("payload", event.get("data"))
    metadata = {key: event[key] for key in ("session", "workspace", "turn", "actor")
                if event.get(key) is not None}
    return Event(id=f"wsc:{event_id}", source_type=f"wsc:{source_type}", payload=payload,
                 source_ref=event.get("source_ref") or event.get("ref"),
                 observed_at=observed if isinstance(observed, str) else None,
                 metadata=metadata or None)


def events_from_wsc(events) -> list[Event]:
    require(isinstance(events, (list, tuple)), "wsc_events_invalid")
    return [from_wsc_event(item) for item in events]


__all__ = ["from_wsc_event", "events_from_wsc"]
