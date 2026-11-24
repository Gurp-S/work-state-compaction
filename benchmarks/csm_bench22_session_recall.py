"""Offline candidate for retrieving continuations within an explicit session."""
from csm_bench22_raw_memory import RawMemoryBench22


class SessionRecallBench22(RawMemoryBench22):
    def _source_neighbors(self, ranked, visible):
        anchors = [index for index in ranked[:3] if self.turns[index].get('session_id')]
        if not anchors:
            return super()._source_neighbors(ranked, visible)

        reserved = set(ranked[:9])
        immediate = []
        extended = []
        for anchor in anchors:
            session = self.turns[anchor]['session_id']
            for step in (-1, 1):
                for distance, lane in ((1, immediate), (2, extended)):
                    index = anchor + step * distance
                    if index not in visible or self.turns[index].get('session_id') != session:
                        break
                    if index not in reserved:
                        lane.append(index)
        return list(dict.fromkeys(immediate + extended))[:6]
