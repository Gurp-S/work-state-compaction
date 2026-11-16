"""Render a bounded, explicitly incomplete set of request candidates."""


def with_candidates(group, candidates):
    omitted = group['candidate_count'] - len(candidates)
    details = ' | '.join(item['text'] for item in candidates)
    suffix = f'；另有 {omitted} 项因交付预算或来源条件未呈现' if omitted else ''
    coverage = '；候选仅来自已审核记录，原文可能还有其他事项' if group.get('coverage') else ''
    return {**group, 'candidates': candidates, 'omitted_candidates': omitted,
            'text': f'[PENDING_BINDING] 当前请求指向未确认；已审核候选：{details}{suffix}{coverage}',
            'source_turns': tuple(sorted({turn for item in candidates for turn in item['source_turns']})),
            'source_spans': [span for item in candidates for span in item['source_spans']]}
