"""Independent semantic discovery of literal user passages."""
from csm_bench22_recall_lanes import _passages
from csm_bench22_semantic_candidates import SemanticCandidates


class SemanticPassages:
    def __init__(self, history, embedder):
        self.passages = []
        self.ends = [0]
        for turn in history:
            self.passages.extend(_passages(turn['turn'], 'user', turn['user'], False))
            self.ends.append(len(self.passages))
        self.index = SemanticCandidates(
            [{'turn': index, 'user': passage.text} for index, passage in enumerate(self.passages)], embedder)

    def rank(self, questions, visible_positions, *, limit=5):
        """Choose one original passage per visible turn; retain exact source offsets."""
        if not 1 <= limit <= 8:
            raise ValueError('invalid_semantic_passage_limit')
        scopes = [[position for turn in scope for position in range(self.ends[turn], self.ends[turn + 1])]
                  for scope in visible_positions]
        candidates = self.index.rank(questions, scopes, limit=32)
        result = []
        for ranked in candidates:
            by_turn = {}
            for position in ranked:
                passage = self.passages[position]
                by_turn.setdefault(passage.turn, passage.receipt())
                if len(by_turn) == limit:
                    break
            result.append(list(by_turn.values()))
        return result
