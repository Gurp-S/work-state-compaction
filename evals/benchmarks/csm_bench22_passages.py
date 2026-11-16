"""Select contiguous, literal passages within the existing evidence budget."""
import re

from bench22.systems import tokens


def _excerpt(field, wanted, limit):
    if len(field) <= limit:
        return field
    spans = [match.span() for match in re.finditer(r'[^\n。！？]+(?:[。！？]|$)?', field)]
    if not spans:
        return field[:limit]
    def score(span):
        terms = set(tokens(field[span[0]:span[1]]))
        return sum(len(term) for term in wanted & terms)
    start, end = max(spans, key=score)
    if end - start >= limit:
        # Long unbroken messages still have a contiguous window around a match.
        first_hit = min((field.find(term, start, end) for term in wanted if len(term) >= 2
                         and field.find(term, start, end) >= 0), default=start)
        start = max(start, first_hit - limit // 4)
        return field[start:start + limit]
    start = max(0, start - (limit - (end - start)) // 3)
    return field[start:start + limit]


def source_passage(source, question, limit=760):
    """A role-preserving view; omitted text is inaccessible to the producer."""
    wanted = set(tokens(question))
    user_limit = min(len(source['user']), int(limit * 0.72))
    assistant_limit = min(len(source['assistant']), limit - user_limit)
    user_limit = min(len(source['user']), limit - assistant_limit)
    return {**source, 'user': _excerpt(source['user'], wanted, user_limit),
            'assistant': _excerpt(source['assistant'], wanted, assistant_limit),
            '_full': source}
