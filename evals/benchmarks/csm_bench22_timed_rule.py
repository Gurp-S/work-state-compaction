"""Publish a reviewed rule for an explicitly bound scope and time window."""
from csm_bench22 import StateRetrieval
from csm_bench22_reviewed_evidence import fit_state_evidence
from csm_bench22_scope import visible_observations
from wsc.csm.contracts import parse_instant
from wsc.csm.state_extraction import render_items


def timed_rule_reference(item):
    turns = '、'.join(map(str, item['source_turns']))
    status = '记录的规则时限已结束' if item['kind'] == 'HISTORICAL' else '适用'
    return (f"[{item['kind']}] {item['slot']}，{status}（第{turns}轮，"
            f"原话时间 {item['source_observed_at']}，"
            f"规则时限 {item['valid_from']} 至 {item['valid_until']}，结束时点不含）")


def _rule_at(system, *, source, scope, valid_from, valid_until, now, cutoff_turn, historical=False):
    if (not isinstance(scope, str) or not scope.strip() or source.path != ('user',)
            or not source.quote.strip()):
        raise ValueError('timed_rule_scope_invalid')
    if type(cutoff_turn) is not int or cutoff_turn < 0:
        raise ValueError('timed_rule_cutoff_invalid')
    clock, start, end = map(parse_instant, (now, valid_from, valid_until))
    if start >= end:
        raise ValueError('timed_rule_window_invalid')
    prefix, _, number = source.event_id.partition('/')
    if prefix != 'chat' or not number.isascii() or not number.isdecimal() or int(number) < 1:
        raise ValueError('timed_rule_source_invalid')
    turn = int(number)
    eligible = clock >= end if historical else start <= clock < end
    if (not eligible or turn > min(cutoff_turn, len(system.turns))
            or parse_instant(system.turns[turn - 1]['time']) > clock):
        return None
    original = system._source(turn - 1)
    if source.quote not in original['user']:
        raise ValueError('reviewed_source_quote_mismatch')
    item = {'kind': 'HISTORICAL' if historical else 'CONDITIONAL_RULE',
            'slot': scope, 'valid_from': valid_from,
            'valid_until': valid_until, 'source_turns': [turn],
            'source_observed_at': original['time'],
            'source_spans': [{'event_id': source.event_id, 'path': ['user'], 'quote': source.quote}]}
    item['text'] = timed_rule_reference(item)
    return item


def retrieve_with_timed_rule(system, question, *, now, cutoff_turn, binding, historical=False):
    """Opt-in retrieval of one caller-reviewed binding alongside ordinary memory."""
    item = _rule_at(system, now=now, cutoff_turn=cutoff_turn, historical=historical, **binding)
    if item is None:
        return system.retrieve(question, now, cutoff_turn)
    return system.retrieve(question, now, cutoff_turn, _reviewed_state=(item,))


def retrieve_timed_rule(system, *, source, scope, valid_from, valid_until, now, cutoff_turn):
    item = _rule_at(system, source=source, scope=scope, valid_from=valid_from,
                    valid_until=valid_until, now=now, cutoff_turn=cutoff_turn)
    items = [{'kind': 'CLOCK', 'now': now}]
    if item is None:
        items.append({'kind': 'NO_CONFIRMED_STATE', 'reason': 'timed_rule_not_visible_or_active',
                      'text': '[NO_CONFIRMED_STATE] 当前没有适用的已绑定时限规则。'})
        return StateRetrieval(items, render_items(items), '', [])
    items.append(item)
    visible = visible_observations(system.turns, cutoff_turn, parse_instant(now))
    heading = '【证据｜仅支撑】\n【聊天记录】'
    items, text, blocks, _, spans = fit_state_evidence(
        items, {}, read_original=system._source, source_block=system._source_block,
        visible=visible, budget=6400, heading=heading)
    evidence = '\n\n'.join([heading, *blocks.values()]) if blocks else ''
    result = StateRetrieval(items, text, evidence, [index + 1 for index in blocks])
    result.meta['evidence_spans'] = spans
    return result
