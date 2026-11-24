"""Budget the producer's date supplement separately from the answer display."""


def date_supplement(dates, sources, read_source, *, allowance=1200):
    extra = {}
    for index in dates:
        if index + 1 in sources:
            continue
        source, block = read_source(index)
        cost = len(block) + 2
        if cost <= allowance:
            extra[index] = (source, block)
            allowance -= cost
    return extra


def fit_answer_evidence(selected, extra, cited_turns, *, allowance):
    cited = {turn - 1 for turn in cited_turns}
    blocks = {**selected, **{index: row[1] for index, row in extra.items() if index in cited}}
    ordered = sorted(blocks, key=lambda index: index not in cited)
    fitted = {}
    for index in ordered:
        block = blocks[index]
        cost = len(block) + 2
        if cost <= allowance:
            fitted[index] = block
            allowance -= cost
    return fitted
