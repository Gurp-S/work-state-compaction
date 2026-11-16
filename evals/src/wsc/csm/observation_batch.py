"""Reject implicit replacement of several same-source values as a state decision.

An explicit update/CAS supplies an operation. Different source events supply
an order. Several implicit values from one source supply neither: they may be
parallel facts, a list, or a correction. Keep them pending without guessing.
"""
from ..contracts import encode
from .contracts import identity_key
from .observation_policy import restates


def ambiguous_indexes(candidates: list[dict]) -> set[int]:
    groups = {}
    for index, candidate in enumerate(candidates):
        if (candidate["intent"] != "auto" or candidate["expected_revision"] is not None
                or candidate.get("valid_from") is not None):
            continue
        key = (identity_key(candidate["entity"], candidate["slot"], candidate["contexts"]),
               tuple(sorted(candidate["source_ids"])))
        signature = encode([candidate["value"], candidate["status"],
                            candidate["lifecycle"], candidate["semantic_type"]])
        groups.setdefault(key, []).append((index, signature))
    return {index for group in groups.values() if len({signature for _, signature in group}) > 1
            for index, _ in group}


def implicit_same_source_replacement(previous: dict | None, candidate: dict, *,
                                     allow_restatement: bool = False) -> bool:
    if (previous is None or candidate["intent"] != "auto"
            or candidate["expected_revision"] is not None or candidate.get("valid_from") is not None):
        return False
    if allow_restatement and restates(previous, candidate):
        return False
    return (set(previous["source_refs"]) == set(candidate["source_ids"])
            and encode([previous["value"], previous["status"], previous["lifecycle"]])
            != encode([candidate["value"], candidate["status"], candidate["lifecycle"]]))
