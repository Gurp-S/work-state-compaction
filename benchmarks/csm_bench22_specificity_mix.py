"""Offline lexical mix with protected leading results and two alternate candidates."""
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_specificity_recall import SpecificityRecallBench22


class SpecificityMixBench22(SpecificityRecallBench22):
    def _rank_sources(self, question, visible):
        baseline = RawMemoryBench22._rank_sources(self, question, visible)
        if self.tail_start is not None or len(baseline) <= 6:
            return baseline
        alternate = super()._rank_sources(question, visible)
        retained = set(baseline[:14])
        extra = [position for position in alternate[:8] if position not in retained][:2]
        return list(dict.fromkeys([*baseline[:6], *extra, *baseline[6:]]))
