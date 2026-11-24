"""Offline dense retrieval over user originals, scoped before ranking."""
import numpy as np


class SemanticCandidates:
    def __init__(self, history, embedder):
        self.turns = tuple(turn['turn'] for turn in history)
        self.embedder = embedder
        self.documents = embedder.embed([turn['user'] for turn in history])
        if self.documents.ndim != 2 or len(self.documents) != len(history) or not np.isfinite(self.documents).all():
            raise ValueError('invalid_semantic_documents')

    def rank(self, questions, visible_positions, *, limit=5):
        if len(questions) != len(visible_positions) or not 1 <= limit <= 32:
            raise ValueError('invalid_semantic_query_batch')
        if not questions:
            return []
        vectors = self.embedder.query_batch(questions)
        if vectors.shape != (len(questions), self.documents.shape[1]) or not np.isfinite(vectors).all():
            raise ValueError('invalid_semantic_query_vectors')
        scores = vectors @ self.documents.T
        results = []
        for row, visible in zip(scores, visible_positions):
            indices = np.asarray(list(visible), dtype=np.intp)
            if np.any(indices < 0) or np.any(indices >= len(self.turns)):
                raise ValueError('invalid_semantic_visibility')
            order = np.lexsort((indices, -row[indices]))[:limit]
            results.append([self.turns[index] for index in indices[order]])
        return results
