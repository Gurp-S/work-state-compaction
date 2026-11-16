"""Offline recall of reviewed rules from explicit current-scene cues."""
from dataclasses import dataclass
import re

from csm_bench22 import StateRetrieval
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_reviewed_evidence import fit_state_evidence
from csm_bench22_scope import visible_observations
from wsc.csm.contracts import parse_instant
from wsc.csm.semantic_contract import SourceSpan
from wsc.csm.state_extraction import render_items


_WORK_CUES = {
    'working': re.compile(r'^\s*(?:我)?(?:刚开始上班|刚开始工作|刚到(?:单位|公司|办公室)(?:坐下)?[，,、 ]*(?:准备|正要)开工)'),
    'off_work': re.compile(r'^\s*(?:我)?刚下班(?:[回到]家|了|[，,。！!\n]|$)'),
}


@dataclass(frozen=True)
class ReviewedConditionalRule:
    scope: str
    condition: str
    source: SourceSpan
    outcome: str | None = None


def _work_context(question):
    if re.search(r'\?|？|不是|没下班|没上班|还在加班|又要回去上班', question):
        return None
    return next((phase for phase, pattern in _WORK_CUES.items() if pattern.match(question)), None)


class ConditionalRecallBench22(RawMemoryBench22):
    """A candidate lane requiring a caller-reviewed conditional rule and scope."""

    def __init__(self):
        super().__init__()
        self.rules = []

    def add_reviewed_rule(self, rule):
        if (not rule.scope or rule.condition not in _WORK_CUES or rule.source.path != ('user',)
                or (rule.outcome is not None and (
                    not isinstance(rule.outcome, str) or not rule.outcome.strip() or rule.outcome != rule.outcome.strip()))):
            raise ValueError('conditional_rule_invalid')
        prefix, _, number = rule.source.event_id.partition('/')
        if prefix != 'chat' or not number.isascii() or not number.isdecimal():
            raise ValueError('conditional_rule_source_invalid')
        turn = int(number)
        if not 1 <= turn <= len(self.turns) or not rule.source.quote.strip() or rule.source.quote not in self._source(turn - 1)['user']:
            raise ValueError('conditional_rule_source_invalid')
        if rule not in self.rules:
            self.rules.append(rule)

    def rewind(self, token):
        super().rewind(token)
        self.rules = [rule for rule in self.rules if int(rule.source.event_id.split('/')[1]) <= token]

    def condition_candidates(self, question, *, now, cutoff_turn, limit=5, rule_scope=None):
        visible = self._search_scope(now, cutoff_turn, limit)
        context = _work_context(question)
        matches = []
        for rule in self.rules:
            turn = int(rule.source.event_id.split('/')[1])
            if rule.condition != context or turn - 1 not in visible or (rule_scope is not None and rule.scope != rule_scope):
                continue
            source = self.read_original(turn, now=now, cutoff_turn=cutoff_turn)
            if rule.source.quote not in source['user']:
                raise ValueError('conditional_rule_source_invalid')
            matches.append({'scope': rule.scope, 'condition': context, 'turn': turn, 'quote': rule.source.quote,
                            'outcome': rule.outcome})
            if len(matches) > limit:
                return {'context': context, 'candidates': matches[:limit], 'truncated': True}
        return {'context': context, 'candidates': matches, 'truncated': False}

    def retrieve_condition(self, question, now, cutoff_turn, *, rule_scope):
        if not isinstance(rule_scope, str) or not rule_scope.strip():
            raise ValueError('conditional_rule_scope_required')
        search = self.condition_candidates(question, now=now, cutoff_turn=cutoff_turn, rule_scope=rule_scope)
        matched = search['candidates']
        items = [{'kind': 'CLOCK', 'now': now}]
        if not matched or search['truncated']:
            reason = 'conditional_candidates_truncated' if search['truncated'] else 'conditional_rule_not_visible_or_applicable'
            items.append({'kind': 'NO_CONFIRMED_STATE', 'reason': reason,
                          'text': '[NO_CONFIRMED_STATE] 当前条件下没有可交付的规则。'})
            return StateRetrieval(items, render_items(items), '', [])

        refs = sorted({match['turn'] for match in matched})
        outcomes = {(match['outcome'], None if match['outcome'] is not None else match['quote'])
                    for match in matched}
        ambiguous = len(outcomes) > 1
        kind = 'PENDING_BINDING' if ambiguous else 'CONDITIONAL_RULE'
        refs_text = ','.join(map(str, refs))
        condition = search['context']
        item = {'kind': kind, 'slot': rule_scope, 'condition': condition,
                'text': f'[{kind}] {rule_scope} / {condition}；来源轮次 {refs_text}',
                'source_turns': refs, 'source_spans': [{'event_id': f'chat/{match["turn"]}', 'path': ['user'],
                                                       'quote': match['quote']} for match in matched]}
        if ambiguous:
            item['reason'] = 'multiple_reviewed_rules'
        else:
            item['value'] = matched[0]['outcome'] or matched[0]['quote']
            item['text'] = f'[{kind}] {rule_scope} / {condition}：{item["value"]}（来源轮次 {refs_text}）'
        items.append(item)
        heading = '【证据｜仅支撑】\n【聊天记录】'
        visible = visible_observations(self.turns, cutoff_turn, parse_instant(now))
        items, text, evidence, _, spans = fit_state_evidence(items, {}, read_original=self._source,
                                                       source_block=self._source_block, visible=visible,
                                                       budget=6400, heading=heading)
        rendered = '\n\n'.join([heading, *(evidence[index] for index in sorted(evidence))]) if evidence else ''
        turns = [index + 1 for index in sorted(evidence)]
        result = StateRetrieval(items, text, rendered, turns)
        result.meta.update(evidence_turns=turns, evidence_spans=spans)
        return result
