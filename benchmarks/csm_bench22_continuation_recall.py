"""Offline recall candidate for explicit continuation cues in adjacent turns."""
from csm_bench22_neighbor_order import continues_previous
from csm_bench22_raw_memory import RawMemoryBench22


class ContinuationRecallBench22(RawMemoryBench22):
    def __init__(self):
        super().__init__(append_passages=True)

    def _extra_passage_positions(self, question, visible, retained):
        found = {}
        for anchor in sorted(retained):
            for continuation in (anchor, anchor + 1):
                previous = continuation - 1
                if previous - 1 not in visible or continuation - 1 not in visible:
                    continue
                other = previous if continuation == anchor else continuation
                if other in retained or other - 1 in found:
                    continue
                before, after = self.turns[previous - 1], self.turns[continuation - 1]
                if before['time'][:10] == after['time'][:10] and continues_previous(after['user']):
                    found[other - 1] = None
        return found.keys()
