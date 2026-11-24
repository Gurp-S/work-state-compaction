"""Opt-in same-source coverage presentation; source/quote selection is unchanged."""
import json

from .codex import CodexCheckpointAdapter
from ..contracts import encode
from ..observation_coverage import covered_facts


class CoveredCodexCheckpointAdapter(CodexCheckpointAdapter):
    @staticmethod
    def capabilities():
        return {**CodexCheckpointAdapter.capabilities(), "adapter": "codex_covered_checkpoint_v1"}

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        items = super().render(body, sources, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        facts = json.loads(items[0]["content"][0]["text"])
        items[0]["content"][0]["text"] = encode(covered_facts(body, items, facts))
        return items
