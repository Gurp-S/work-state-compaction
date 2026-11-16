"""Opt-in projection of separately attributed reports about one reviewed issue."""
from dataclasses import dataclass

from csm_bench22 import StateRetrieval
from csm_bench22_raw_memory import RawMemoryBench22
from csm_bench22_reviewed_evidence import fit_state_evidence
from wsc.csm.semantic_contract import SourceSpan
from wsc.csm.state_extraction import render_items


@dataclass(frozen=True)
class ReportedClaim:
    speaker: str
    source: SourceSpan


@dataclass(frozen=True)
class ReviewedDispute:
    issue: str
    claims: tuple[ReportedClaim, ReportedClaim]
    reviewed_through: int


def reported_dispute_item(dispute, *, read_original):
    if len(dispute.claims) != 2 or len({claim.speaker for claim in dispute.claims}) != 2:
        raise ValueError('dispute_distinct_speakers_required')
    spans = []
    refs = set()
    for claim in dispute.claims:
        prefix, _, number = claim.source.event_id.partition('/')
        quote = claim.source.quote
        if (prefix != 'chat' or not number.isascii() or not number.isdecimal() or claim.source.path != ('user',)
                or not claim.speaker.strip() or claim.speaker not in quote):
            raise ValueError('dispute_report_source_invalid')
        turn = int(number)
        if quote not in read_original(turn)['user']:
            raise ValueError('dispute_report_source_invalid')
        refs.add(turn)
        spans.append({'event_id': claim.source.event_id, 'path': ['user'], 'quote': quote})
    if spans[0]['quote'] == spans[1]['quote']:
        raise ValueError('dispute_distinct_reports_required')
    text = f'[CONFLICT_UNRESOLVED] {dispute.issue}；截至第 {dispute.reviewed_through} 轮，双方说法未核实'
    text += '；' + ' / '.join(f'用户转述 {claim.speaker}：「{claim.source.quote}」' for claim in dispute.claims)
    return {'kind': 'CONFLICT_UNRESOLVED', 'text': text, 'source_turns': sorted(refs),
            'status': 'reviewed_reports', 'source_spans': spans,
            'reported_by': [claim.speaker for claim in dispute.claims], 'confirmed': False}


class ReportedDisputeBench22(RawMemoryBench22):
    def retrieve_dispute(self, now, cutoff_turn, *, issue, dispute):
        visible = self._search_scope(now, cutoff_turn, 1)
        items = [{'kind': 'CLOCK', 'now': now}]
        if not issue.strip() or issue != dispute.issue or cutoff_turn != dispute.reviewed_through or len(visible) != cutoff_turn:
            reason = 'reviewed_dispute_scope_unavailable'
            items.append({'kind': 'NO_CONFIRMED_STATE', 'reason': reason,
                          'text': '[NO_CONFIRMED_STATE] 当前请求范围内无可发布的已审核冲突。'})
            return StateRetrieval(items, render_items(items), '', [])
        items.append(reported_dispute_item(dispute, read_original=lambda turn:
                                           self.read_original(turn, now=now, cutoff_turn=cutoff_turn)))
        heading = '【证据｜仅支撑】\n【聊天记录】'
        items, text, blocks, _, spans = fit_state_evidence(items, {}, read_original=self._source,
                                                            source_block=self._source_block, visible=visible,
                                                            budget=6400, heading=heading)
        turns = [index + 1 for index in sorted(blocks)]
        evidence = '\n\n'.join([heading, *(blocks[turn - 1] for turn in turns)]) if turns else ''
        result = StateRetrieval(items, text, evidence, turns)
        result.meta.update(evidence_turns=turns, evidence_spans=spans)
        return result
