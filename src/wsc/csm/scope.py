"""Canonical scopes for repository memories.

A memory lives in exactly one scope. A branch lookup may widen to its repository and then
to the entity level, but widening never crosses repositories. Scope strings are built here
so identity keys never depend on hand-typed separators.
"""
from __future__ import annotations

from .contracts import normalize, require

ENTITY = "entity"
_SEP = "|"


def _token(value, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{field}_missing")
    return "_".join(normalize(value, field=field).split()).replace("/", "__")


def repo_scope(repo: str) -> str:
    """Repository-wide facts: `repo:owner__name`."""
    return "repo:" + _token(repo, "repo")


def branch_scope(repo: str, branch: str) -> str:
    """Branch-scoped state; inherits repository facts when a lookup widens."""
    return repo_scope(repo) + _SEP + "branch:" + _token(branch, "branch")


def chain(scope: str | None) -> tuple[str, ...]:
    """Most specific scope first, always ending at the entity level."""
    if not scope or scope == ENTITY:
        return (ENTITY,)
    parts = str(scope).split(_SEP)
    out = [_SEP.join(parts[:index]) for index in range(len(parts), 0, -1)]
    if ENTITY not in out:
        out.append(ENTITY)
    return tuple(out)


def origin(identity: dict) -> str:
    """The scope the writer asked for; event identities partition on observation scope."""
    return identity.get("origin_scope") or identity.get("scope") or ENTITY


def allows(origin_scope: str, wanted: str | None, *, widen: bool = False) -> bool:
    if not wanted:
        return True
    if origin_scope == wanted:
        return True
    return widen and origin_scope in chain(wanted)


def specificity(origin_scope: str, wanted: str | None, *, widen: bool) -> int:
    """0 is the requested scope; larger values are more general ancestors."""
    if not wanted:
        return 0
    if origin_scope == wanted:
        return 0
    if not widen:
        return len(chain(wanted))
    try:
        return chain(wanted).index(origin_scope)
    except ValueError:
        return len(chain(wanted))


__all__ = ["ENTITY", "repo_scope", "branch_scope", "chain", "origin", "allows",
           "specificity"]
