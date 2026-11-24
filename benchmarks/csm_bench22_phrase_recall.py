"""Exact phrase and number-with-unit candidates, with role and cutoff scope."""
from array import array
from collections import defaultdict
import math
import re


_CHINESE = re.compile(r'[\u3400-\u9fff]+')
_NUMBER_UNIT = re.compile(r'(?<![\d.])\d+(?:\.\d+)?\s*(?:元|块|页|斤|公斤|千克|公里|毫米|厘米|米|岁|次|封|本|小时|分钟|%)')


def phrase_terms(text):
    terms = {match.group().replace(' ', '') for match in _NUMBER_UNIT.finditer(text)}
    for match in _CHINESE.finditer(text):
        word = match.group()
        terms.update(word[index:index + 3] for index in range(len(word) - 2))
    return terms


class PhraseIndex:
    def __init__(self):
        self.postings = defaultdict(lambda: array('I'))

    def add(self, turn):
        offset = (turn['turn'] - 1) * 2
        for role, field in enumerate(('user', 'assistant')):
            for term in phrase_terms(turn[field]):
                self.postings[term].append(offset + role)

    def rewind(self, dropped_turns):
        for turn in reversed(dropped_turns):
            offset = (turn['turn'] - 1) * 2
            for role, field in ((1, 'assistant'), (0, 'user')):
                for term in phrase_terms(turn[field]):
                    posting = self.postings[term]
                    if posting.pop() != offset + role:
                        raise ValueError('phrase_index_rewind_mismatch')
                    if not posting:
                        del self.postings[term]

    def search(self, question, visible, limit):
        scores = defaultdict(float)
        for term in sorted(phrase_terms(question)):
            weights = {}
            for encoded in self.postings.get(term, ()):
                offset, role = divmod(encoded, 2)
                if offset in visible:
                    weights.setdefault(offset, 1.0 if role == 0 else 0.5)
            if not weights:
                continue
            rarity = math.log1p((len(visible) - len(weights) + 0.5) / (len(weights) + 0.5))
            for offset, role_weight in weights.items():
                scores[offset] += rarity * role_weight
        return [offset + 1 for offset in sorted(scores, key=lambda i: (-scores[i], i))[:limit]]
