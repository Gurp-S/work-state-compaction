"""Isolated comparison of source-backed observations of named reading material."""
from collections import defaultdict
import re

from csm_bench22 import StateRetrieval
from csm_bench22_passage_binding import verify_passage
from csm_bench22_raw_memory import RawMemoryBench22
from wsc.csm.cem.state_extraction import render_items


_WHICH = re.compile(r'哪(?:一)?本')
_RANK = re.compile(r'最(?:多|少|长|短|靠后|接近|高|低|快|慢)')
_PROGRESS = re.compile(r'进度|读了几成|读得最靠后|读完了多少|读了百分之')
_UNCERTAIN = re.compile(r'不是|并非|记错|误记|不确定|大概|好像|可能|还剩|页左右|章左右|[？?]')
_READING = re.compile(r'读到|看到|读完|睡前.*(?:读|看|翻)')
_FINISHED = re.compile(r'(?:终于|已经|刚刚|我)(?:把[^。！？]{1,48})?读完')
_TITLE = re.compile(r'《([^《》\n]{1,48})》')
_DIGITS = '零一二三四五六七八九'
_NUMBER = r'[0-9零〇一二两三四五六七八九十百千]{1,7}'
_TOTAL = re.compile(rf'(?:全书|全篇|总共|总计|共计)(?:有)?\s*({_NUMBER})\s*([页章])')
_POSITION = re.compile(rf'(?:读|看|翻)到第?\s*({_NUMBER})\s*([页章])')
_UNITS = {'千': 1000, '百': 100, '十': 10}
_VALID_NUMBER = re.compile(r'(?:[一二两三四五六七八九]千)?(?:零?[一二两三四五六七八九]百)?'
                           r'(?:零?[一二三四五六七八九]?十)?(?:零?[一二三四五六七八九])?')


def comparison_metric(question):
    if not _WHICH.search(question) or not _RANK.search(question) or '读' not in question:
        return None
    if _PROGRESS.search(question):
        return 'progress'
    return 'pages' if '页数' in question else None


def _number(text):
    if text.isascii():
        return int(text)
    text = text.replace('〇', '零').replace('两', '二')
    if not _VALID_NUMBER.fullmatch(text):
        return 0
    value = 0
    for unit, multiplier in _UNITS.items():
        if unit in text:
            digit, text = text.split(unit)
            value += (_DIGITS.index(digit[-1]) if digit else 1) * multiplier
    return value + (_DIGITS.index(text[-1]) if text else 0)


def _observations(turn):
    for clause in re.finditer(r'[^\n。！？；]+[。！？；]?', turn['user']):
        quote = clause.group()
        titles, totals, positions = _TITLE.findall(quote), _TOTAL.findall(quote), _POSITION.findall(quote)
        if (len(quote) > 240 or len(titles) != 1 or len(totals) != 1 or len(positions) > 1
                or _UNCERTAIN.search(quote) or not _READING.search(quote)):
            continue
        raw, unit = totals[0]
        total = _number(raw)
        current = _number(positions[0][0]) if positions and positions[0][1] == unit else 0
        if total <= 0 or current > total:
            continue
        yield {'title': titles[0], 'unit': unit, 'total': total, 'position': current or None,
               'finished': bool(_FINISHED.search(quote)),
               'source': {'turn': turn['turn'], 'field': 'user', 'start': clause.start(),
                          'end': clause.end(), 'quote': quote}}


class ReadingComparisonBench22(RawMemoryBench22):
    def __init__(self):
        super().__init__()
        self.reading_observations = []

    def _index_source(self, turn):
        super()._index_source(turn)
        self.reading_observations.extend(_observations(turn))

    def rewind(self, token):
        super().rewind(token)
        self.reading_observations = [row for row in self.reading_observations if row['source']['turn'] <= token]

    def comparison_candidates(self, question, *, now, cutoff_turn, preferred_turns=()):
        metric = comparison_metric(question)
        if metric is None:
            return None, []
        visible = self._search_scope(now, cutoff_turn, 1)
        named = set(_TITLE.findall(question))
        by_title = defaultdict(list)
        for row in self.reading_observations:
            if row['source']['turn'] - 1 in visible and (not named or row['title'] in named):
                by_title[row['title']].append(row)
        if not 2 <= len(by_title) <= 6 or named and named != set(by_title):
            return metric, []
        preferred = set(preferred_turns)
        selected = []
        for observations in by_title.values():
            if len({(row['unit'], row['total']) for row in observations}) != 1:
                return metric, []
            if metric == 'progress':
                known = [row for row in observations if row['position'] is not None]
                if not known or any(row['finished'] for row in observations):
                    continue
                # A completed reading or conflicting progress requires its own transition binding.
                if len({row['position'] for row in known}) != 1 or known[-1]['position'] >= known[-1]['total']:
                    continue
                observations = known
            elif observations[-1]['unit'] != '页':
                continue
            selected.append(next((row for row in reversed(observations)
                                  if row['source']['turn'] in preferred), observations[-1]))
        return metric, selected if len(selected) >= 2 else []

    def supplement_comparison(self, result, question, *, now, cutoff_turn):
        if self.tail_start is not None or 'evidence_spans' in result.meta:
            return result
        metric, members = self.comparison_candidates(
            question, now=now, cutoff_turn=cutoff_turn, preferred_turns=result.used_turns)
        if not members:
            return result
        old_turns = result.meta.get('evidence_turns', result.used_turns)
        if old_turns != result.used_turns:
            return result
        blocks = {turn: self._source_block(self.read_original(turn, now=now, cutoff_turn=cutoff_turn))
                  for turn in old_turns}
        heading = '【证据｜仅支撑】\n【聊天记录】'
        expected = '\n\n'.join([heading, *blocks.values()]) if blocks else ''
        if expected != result.evidence:
            return result
        prior = [item for item in result.state_items if item['kind'] != 'NO_CONFIRMED_STATE']
        protected = {turn for item in prior for turn in item.get('source_turns', ())}
        if not protected <= blocks.keys():
            return result
        spans, measurements = [], []
        projected = {turn: block for turn, block in blocks.items() if turn in protected}
        occupied = set()
        for row in members:
            cite = row['source']
            turn, quote = cite['turn'], cite['quote']
            source = self.read_original(turn, now=now, cutoff_turn=cutoff_turn)
            verify_passage(cite, source)
            if turn in occupied:
                return result
            occupied.add(turn)
            if turn not in protected:
                projected[turn] = self._source_block({**source, '_full': source, 'user': quote, 'assistant': ''})
                spans.append({'event_id': f'chat/{turn}', 'path': ['user'], 'quote': quote})
            value = f"{row['total']}{row['unit']}"
            if metric == 'progress':
                value = f"读到 {row['position']}{row['unit']} / 全书 {row['total']}{row['unit']}"
            measurements.append(f"《{row['title']}》{value} [第{turn}轮]")
        item = {'kind': 'OBSERVATION_COMPARISON', 'status': 'scope_unverified', 'metric': metric,
                'scope_complete': False, 'source_turns': sorted(occupied),
                'citations': [row['source'] for row in members], 'observations': members,
                'text': '[OBSERVATION_COMPARISON] 已观察的候选，集合范围与当前适用性未确认。\n' +
                        '\n'.join(measurements)}
        if metric == 'progress' and len({row['unit'] for row in members}) > 1:
            item['text'] += '\n页与章是不同计量口径。'
        items = [*prior, item]
        state = render_items(items)
        remaining = 6400 - len(state) - 2 - len(heading)
        remaining -= sum(2 + len(block) for block in projected.values())
        if remaining < 0:
            return result
        for turn, block in blocks.items():
            cost = 2 + len(block)
            if turn not in projected and cost <= remaining:
                projected[turn] = block
                remaining -= cost
        turns = sorted(projected)
        evidence = '\n\n'.join([heading, *(projected[turn] for turn in turns)])
        packet = StateRetrieval(items, state, evidence, turns)
        packet.meta.update({**result.meta, 'state_items': items, 'evidence_turns': turns, 'evidence_spans': spans})
        return packet
