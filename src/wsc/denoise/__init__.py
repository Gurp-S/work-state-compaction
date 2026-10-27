"""Deterministic view-level denoising. Sources are never modified.

Every rule takes the snapshot rows, returns new rows plus one action per source
it touched. An action records the rule id, the source id, the byte delta and a
pointer that can be used to get the original bytes back.
"""
from .registry import Action, RULES, apply_rules
from .report import summarize

__all__ = ["Action", "RULES", "apply_rules", "summarize"]
