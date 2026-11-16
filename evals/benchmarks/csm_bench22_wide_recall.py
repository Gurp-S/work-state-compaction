"""Offline candidate for removing early lexical truncation before rank fusion."""
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_scope import rank_visible


class WideRecallBench22(RawMemoryBench22):
    def _rank_sources(self, question, visible):
        return rank_visible(question, self.turns, visible, self.user_index, self.full_index, lane_limit=64)
