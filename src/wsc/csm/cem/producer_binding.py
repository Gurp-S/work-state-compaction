"""Keep read-time producer claims inside the reviewed request scope."""


def _ranges(text, quote):
    start = text.find(quote)
    while start >= 0:
        yield start, start + len(quote)
        start = text.find(quote, start + 1)


def outside_pending_scope(produced, pending_spans, *, sources):
    """Suppress claims based on original spans reserved for unresolved candidates."""
    reserved = {}
    for span in pending_spans:
        key = span['event_id'], tuple(span['path'])
        reserved.setdefault(key, []).append(span['quote'])
    if not reserved:
        return produced
    def overlaps(cite):
        quotes = reserved.get((f"chat/{cite['turn']}", (cite['field'],)), ())
        if not quotes:
            return False
        source = sources[cite['turn']]
        original = source.get('_full', source)[cite['field']]
        return any(start < upper and lower < end
                   for start, end in _ranges(original, cite['quote'])
                   for quote in quotes for lower, upper in _ranges(original, quote))

    return [item for item in produced if not any(overlaps(cite) for cite in item.get('citations', ()))]
