"""Offline comparison of lexical recall without whole-turn length normalization."""
from bench22.systems import IncBM25

from csm_bench22_raw_memory import RawMemoryBench22


class LengthRecallBench22(RawMemoryBench22):
    def __init__(self, **options):
        super().__init__(**options)
        self.user_index = IncBM25(b=0)
        self.full_index = IncBM25(b=0)
