"""Deterministic view-level denoising. Sources are never modified.

Every rule takes the snapshot rows, returns new rows plus one action per source
it touched. An action records the rule id, the source id, the byte delta and a
pointer that can be used to get the original bytes back.

verify() checks the structural guarantees after a pass: identity preserved,
control rows byte-identical, every removed byte has a matching pointer, and every
changed row announces that it changed.
"""
from .registry import Action, RULES, apply_rules, already_denoised
from .report import summarize
from .verify import is_marked, recover, verify

__all__ = ["Action", "RULES", "apply_rules", "already_denoised", "summarize",
           "is_marked", "recover", "verify"]
