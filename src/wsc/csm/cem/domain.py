"""Domain state machines and dependency semantics (§5.2-§5.4, §6).

Two rules live here and nowhere else:

* a semantic type has exactly one legal status vocabulary and one legal transition set;
* a dependency edge only *proposes* impact. The resolver never moves state, because the
  engine cannot know whether a solved permission problem really means deployment resumes.
"""
from __future__ import annotations

from ..contracts import require
from . import relations as graph
from ..contracts import (CSMError, DEPENDENCY_EFFECTS, DEPENDENCY_RELATIONS, DOMAIN_STATUS,
                        DOMAIN_TRANSITIONS, TRUTHS)


def validate_status(semantic_type: str, status: str | None,
                    previous_status: str | None = None) -> None:
    """Reject an unknown status or an illegal move before any revision is written."""
    allowed = DOMAIN_STATUS.get(semantic_type, ())
    if status is None:
        return
    require(status in allowed, "domain_status_unknown")
    if previous_status is None or previous_status == status:
        return
    require(previous_status in allowed, "domain_status_unknown")
    require((previous_status, status) in DOMAIN_TRANSITIONS.get(semantic_type, ()),
            "domain_transition_invalid")


def validate_truth(truth: str) -> None:
    require(truth in TRUTHS, "relation_truth_invalid")


def impact(db, memory_id: str, *, kinds: tuple[str, ...] = DEPENDENCY_RELATIONS) -> dict:
    """List what this state change touches. Direct edges only: impact never cascades."""
    edges = graph.of_ref(db, graph.memory_ref(memory_id), kinds=kinds, direction="out",
                         confirmed_only=True)
    effects, gaps = [], []
    for edge in edges:
        effect, reason = _effect(edge)
        effects.append({"rel_id": edge["rel_id"], "kind": edge["kind"],
                        "subject": edge["subject"], "object": edge["object"],
                        "truth": edge.get("truth"), "effect": effect, "reason": reason})
        if effect == "INFORMATION_GAP" or edge["kind"] == "ASSOCIATION":
            gaps.append(edge["object"])
    return {"memory_id": memory_id, "effects": effects,
            "gaps": list(dict.fromkeys(gaps)), "cascaded": False,
            "invariant": "resolver_proposes_only"}


def _effect(edge: dict) -> tuple[str, str]:
    """§6.2-§6.3: causal and associative edges never auto-recover the effect."""
    kind = edge["kind"]
    if kind == "ASSOCIATION":
        return "NO_EFFECT", "association_does_not_move_state"
    if kind == "CAUSAL":
        return "NO_EFFECT", "cause_does_not_recover_effect"
    truth = edge.get("truth")
    if truth == "TRUE":
        return "REVALIDATE", "premise_true"
    if truth == "FALSE":
        return "REVALIDATE", "premise_false"
    return "INFORMATION_GAP", "premise_unknown"


def assert_effect(effect: str) -> None:
    require(effect in DEPENDENCY_EFFECTS, "dependency_effect_unknown")
