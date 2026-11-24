"""Mechanical lower bound shared by generation admission and view preparation."""
from . import state_view
from .contracts import encode, require
from .control_sources import is_control_source


def mandatory_sources(prefix):
    # No semantic rule silently expires historical user/control messages.
    return [row for row in prefix if is_control_source(row)]


def minimum_view_bytes(prefix, records=()):
    # H1: current ledger entries are presented by default, so they belong to
    # the mandatory lower bound alongside control sources.
    source_ids = {row["id"] for row in prefix}
    current = [record for record in state_view.current_entries(records, prefix)
               if set(record["sources"]) <= source_ids]
    body = {"sources": mandatory_sources(prefix), "understandings": current, "clues": []}
    return len(encode(body).encode("utf-8"))


def admit_generation(prefix, max_view_bytes, records=()):
    require(all(row["kind"] != "opaque" for row in mandatory_sources(prefix)),
            "opaque_hot_selection_unavailable")
    require(minimum_view_bytes(prefix, records) <= max_view_bytes,
            "mandatory_view_byte_budget_exhausted")
