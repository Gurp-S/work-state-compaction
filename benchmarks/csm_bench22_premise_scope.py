"""Keep a numeric question premise separate from cited memory values."""
import re

from wsc.csm.cem.calendar_anchors import _number


_QUANTITY = re.compile(r'(?<![\d零一二两三四五六七八九十百千万点.])'
                       r'([0-9零一二两三四五六七八九十]{1,9})\s*'
                       r'(分钟|小时|公里|公斤|千克|厘米|毫升|块钱|块|元|封|份|个|件|张|本|页|度|天|次|斤|米)')


def _quantities(text):
    found = []
    for match in _QUANTITY.finditer(text):
        try:
            value = _number(match[1])
        except ValueError:
            continue
        unit = '元' if match[2] in ('块', '块钱') else match[2]
        found.append((match.start(), value, unit))
    return found


def scope_numeric_premises(items, question):
    premises = {(number, unit) for _, number, unit in _quantities(question)}
    scoped = []
    for item in items:
        if item['kind'] != 'CURRENT_CONFIRMED' or item.get('status') != 'source_projection':
            scoped.append(item)
            continue
        claimed = _quantities(item['value'])
        if len(claimed) != 1 or claimed[0][0] != 0 or claimed[0][1:] not in premises:
            scoped.append(item)
            continue
        _, number, unit = claimed[0]
        alternatives = [(cite, value) for cite in item.get('citations', ()) if cite['field'] == 'user'
                        for _, value, quote_unit in _quantities(cite['quote']) if quote_unit == unit]
        if not alternatives or any(value == number for _, value in alternatives):
            scoped.append(item)
            continue
        refs = ','.join(map(str, item['source_turns']))
        text = (f'[PENDING_BINDING] {item["entity"]} / {item["slot"]}；题面数值未由引文支持；'
                f'来源轮次 {refs}')
        quotes = list(dict.fromkeys(cite['quote'] for cite, _ in alternatives if len(cite['quote']) <= 160))
        if quotes:
            text += '；用户原话：' + ' / '.join(quotes[:2])
        pending = {key: value for key, value in item.items() if key != 'value'}
        scoped.append({**pending, 'kind': 'PENDING_BINDING', 'text': text, 'reason': 'numeric_premise_source_mismatch'})
    return scoped
