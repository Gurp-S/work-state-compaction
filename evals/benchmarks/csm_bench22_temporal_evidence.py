"""Project calendar coordinates for delivered source text without binding an event."""
from wsc.csm.commitment_candidates import discover_commitment_candidates
from wsc.csm.contracts import parse_instant


def deadline_annotations(source, delivered_block, *, now):
    clock = parse_instant(now)
    result = []
    for candidate in discover_commitment_candidates(f"chat/{source['turn']}", 'user',
                                                   source['user'], source['time']):
        if (candidate.kind != 'deadline_date' or not candidate.day
                or candidate.text not in delivered_block):
            continue
        start, end = map(parse_instant, candidate.day)
        relation = '早于所指日期' if clock < start else '晚于所指日期' if clock >= end else '处于所指日期'
        result.append(f'日期词「{candidate.text}」→ {candidate.day[0][:10]}，当前{relation}（事项未绑定）')
    return list(dict.fromkeys(result))


def fit_deadline_appendix(selected, *, read_source, now, allowance, priority=()):
    """Use spare space and keep derived annotations outside the source blocks."""
    heading = '\n\n【日期换算｜事项未绑定】'
    if allowance <= len(heading):
        return '', []
    allowance -= len(heading)
    rows = []
    positions = dict.fromkeys((*priority, *sorted(selected)))
    for position in positions:
        if position not in selected:
            continue
        block = selected[position]
        source = read_source(position)
        # The role labels delimit a rendered view, while the original field
        # provides an independent check against labels embedded in source text.
        user = block.partition('\n用户：')[2].rpartition('\n助手：')[0]
        if not user or any(part not in source['user'] for part in user.split('\n[…]\n')):
            continue
        for annotation in deadline_annotations(source, user, now=now):
            line = f'\n第{source["turn"]}轮 {annotation}'
            if len(line) <= allowance:
                rows.append({'turn': source['turn'], 'text': annotation})
                allowance -= len(line)
    if not rows:
        return '', []
    return heading + ''.join(f'\n第{row["turn"]}轮 {row["text"]}' for row in rows), rows
