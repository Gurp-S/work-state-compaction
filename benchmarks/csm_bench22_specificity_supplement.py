"""Offline specificity recall using only the unused evidence budget."""
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_specificity_recall import SpecificityRecallBench22


class SpecificitySupplementBench22(SpecificityRecallBench22):
    def __init__(self):
        super().__init__(append_passages=True)

    def _rank_sources(self, question, visible):
        return RawMemoryBench22._rank_sources(self, question, visible)

    def _extra_passage_positions(self, question, visible, retained):
        return super()._rank_sources(question, visible)[:16]
