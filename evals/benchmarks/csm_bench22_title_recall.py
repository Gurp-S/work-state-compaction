"""One-hop lookup for explicitly named works with a missing page total."""
import re

from csm_bench22_candidate_delivery import append_source_candidate
from csm_bench22_raw_memory import RawMemoryBench22

_TITLE = re.compile(r'《([^《》\n]{1,48})》')
_TOTAL = re.compile(r'(?:全书|总共|总计|共计)(?:有)?\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+)\s*页')
_UNCERTAIN = re.compile(r'不是|并非|记错|误记|不确定|大概|好像|可能|吗|[？?]')


class TitleRecallBench22(RawMemoryBench22):
    def __init__(self):
        super().__init__()
        self.page_totals = {}

    def _index_source(self, turn):
        super()._index_source(turn)
        for clause in re.finditer(r'[^\n。！？]+[。！？]?', turn['user']):
            text = clause.group()
            titles = set(_TITLE.findall(text))
            totals = _TOTAL.findall(text)
            if len(titles) == len(totals) == 1 and len(text) <= 155 and not _UNCERTAIN.search(text):
                self.page_totals.setdefault(next(iter(titles)), []).append({
                    'turn': turn['turn'], 'field': 'user', 'start': clause.start(),
                    'end': clause.end(), 'quote': text, 'total': totals[0],
                })

    def rewind(self, token):
        super().rewind(token)
        for title, candidates in list(self.page_totals.items()):
            visible = [candidate for candidate in candidates if candidate['turn'] <= token]
            if visible:
                self.page_totals[title] = visible
            else:
                del self.page_totals[title]

    def supplement_page_totals(self, result, *, now, cutoff_turn):
        if self.tail_start is not None:
            return result
        visible = self._search_scope(now, cutoff_turn, 1)
        for item in result.state_items:
            if (item['kind'] != 'UNKNOWN' or item.get('status') != 'source_projection'
                    or '页数' not in item.get('slot', '')):
                continue
            titles = {title for cite in item.get('citations', ()) if cite['field'] == 'user'
                      and cite['turn'] - 1 in visible and cite['quote'] in self.read_original(
                          cite['turn'], now=now, cutoff_turn=cutoff_turn)['user']
                      for title in _TITLE.findall(cite['quote'])}
            if len(titles) != 1:
                continue
            title, = titles
            matches = [row for row in self.page_totals.get(title, ()) if row['turn'] - 1 in visible]
            if len({row['total'] for row in matches}) != 1:
                continue
            added = append_source_candidate(self, result, matches[-1],
                                            [other for other in result.state_items if other is not item],
                                            now=now, cutoff_turn=cutoff_turn, label=f'《{title}》全书页数候选',
                                            reason='title_edition_binding_unverified')
            if added is not result:
                return added
        return result
