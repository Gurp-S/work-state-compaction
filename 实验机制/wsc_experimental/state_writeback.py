"""H2: refine one turn's observations into ledger entries. Write-back only.

No view is prepared here: the loop edge from observations to State is separate
from the edge from State to Context, so a write-back never publishes anything.
"""
from dataclasses import replace
from time import monotonic
from uuid import uuid4

from wsc import accounting
from wsc.contracts import Generated, Limits, Usage, digest, require


def write_back(core, snapshot, generator, *, producer: str, limits: Limits = Limits()) -> list[dict]:
    material = core.material(snapshot)
    phase = "writeback:" + digest({"source": snapshot.source_digest,
                                   "generation": snapshot.generation})
    attempt = uuid4().hex
    with core.store.transaction() as db:
        accounting.begin(db, attempt, phase)
    start = monotonic()
    try:
        result = generator(material)
        require(isinstance(result, Generated), "generation_result_invalid")
    except BaseException as exc:
        usage = getattr(exc, "usage", Usage())
        if not isinstance(usage, Usage):
            usage = Usage()
        with core.store.transaction() as db:
            accounting.finish(db, attempt, replace(usage, elapsed_ms=(monotonic() - start) * 1000),
                              status="failed")
        raise
    with core.store.transaction() as db:
        accounting.finish(db, attempt, replace(result.usage, elapsed_ms=(monotonic() - start) * 1000))
    return [core.remember(value, producer=producer)
            for value in result.selection.new_understandings]