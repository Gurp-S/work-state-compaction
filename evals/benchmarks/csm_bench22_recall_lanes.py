"""Literal passage candidates with recoverable source offsets."""
from dataclasses import dataclass
import re

from bench22.systems import IncBM25, tokens


@dataclass(frozen=True)
class Passage:
    turn: int
    field: str
    start: int
    end: int
    text: str

    def receipt(self):
        return {'turn': self.turn, 'field': self.field, 'start': self.start,
                'end': self.end, 'quote': self.text}


def _segments(text, sentences):
    start = 0
    for line in text.splitlines(keepends=True):
        if sentences:
            offset = 0
            for boundary in re.finditer(r'[。！？!?；;]+', line):
                end = boundary.end()
                yield start + offset, line[offset:end]
                offset = end
            if offset < len(line):
                yield start + offset, line[offset:]
        else:
            yield start, line
        start += len(line)


def _passages(turn, field, text, sentences):
    for start, line in _segments(text, sentences):
        if line.strip():
            for offset in range(0, len(line), 224):
                end = min(len(line), offset + 288)
                yield Passage(turn, field, start + offset, start + end, line[offset:end])
                if end == len(line):
                    break


def rank_passages_in_turn(turn, query, limit, *, include_next=False):
    passages = [passage for field in ('user', 'assistant')
                for passage in _passages(turn['turn'], field, turn[field], True)]
    if not passages:
        return []
    index = IncBM25()
    for passage in passages:
        index.add(passage.text)
    selected = []
    for position in index.top(query, limit):
        passage = passages[position]
        if include_next and position + 1 < len(passages):
            following = passages[position + 1]
            if (following.field == passage.field and following.start >= passage.end
                    and following.end - passage.start <= 480):
                passage = Passage(passage.turn, passage.field, passage.start, following.end,
                                  turn[passage.field][passage.start:following.end])
        if not any(item.field == passage.field and item.start <= passage.start and item.end >= passage.end
                   for item in selected):
            selected.append(passage)
    return selected


class PassageIndex:
    def __init__(self, *, sentences=False):
        self.sentences = sentences
        self.index = IncBM25()
        self.passages = []
        self.ends = [0]

    def add(self, turn):
        for field in ('user', 'assistant'):
            for passage in _passages(turn['turn'], field, turn[field], self.sentences):
                self.index.add(passage.text)
                self.passages.append(passage)
        self.ends.append(len(self.passages))

    def rewind(self, stop):
        end = self.ends[stop]
        self.index.truncate(end)
        del self.passages[end:]
        del self.ends[stop + 1:]

    def search(self, query, visible, limit, *, distinct_passages=False):
        if not visible or not self.passages:
            return []
        if len(visible) == len(self.ends) - 1:
            index, passages = self.index, self.passages
        else:
            index = IncBM25()
            passages = []
            for offset in visible:
                for passage in self.passages[self.ends[offset]:self.ends[offset + 1]]:
                    index.add(passage.text)
                    passages.append(passage)
        if not passages:
            return []
        best = {}
        alternate = []
        for offset in index.top(query, min(len(passages), 8 * limit)):
            passage = passages[offset]
            if distinct_passages and passage.turn in best:
                alternate.append(passage)
            best.setdefault(passage.turn, passage)
            if len(best) == limit and not distinct_passages:
                break
        selected = list(best.values())[:limit]
        if not distinct_passages:
            return selected
        requested = {term for term in tokens(query) if len(term) >= 2}
        # Preserve the primary ranking and cap additions separately.
        extra_limit = min(2, 32 - len(selected))
        by_turn = {item.turn: item for item in selected}
        supplemented = set()
        for candidate in alternate:
            if len(supplemented) == extra_limit:
                break
            first = by_turn.get(candidate.turn)
            if first is None or candidate.field != 'user' or candidate.turn in supplemented:
                continue
            if first.field == candidate.field and candidate.start < first.end and first.start < candidate.end:
                continue
            terms = set(tokens(candidate.text))
            if requested.intersection(terms) - set(tokens(first.text)):
                selected.append(candidate)
                supplemented.add(candidate.turn)
        return selected
