"""Loss metadata composes across retrieval and assembly stages.

Omissions counted here are local; an upstream truncation has an unknown size
unless its producer supplies one. Neither absence of truncation nor a local
zero means that the complete history has been searched.
"""


def loss_scope(upstream: dict, omitted: int) -> dict:
    inherited = bool(upstream.get("truncated"))
    return {"omitted": omitted, "upstream_truncated": inherited,
            "truncated": inherited or omitted > 0}
