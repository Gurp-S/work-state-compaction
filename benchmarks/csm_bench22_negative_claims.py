"""Quarantine a produced negative claim absent from its cited user text."""
import re


_CLAUSE = re.compile(r'[^，。；！？、,;!?\n]+')
_NEGATIVE = re.compile(r'(?:尚未|还没(?:有)?|至今未|从未|没有|没再|不曾)(?=\S)')


def scope_negative_claims(items):
    scoped = []
    for item in items:
        if item['kind'] != 'CURRENT_CONFIRMED' or item.get('status') != 'source_projection':
            scoped.append(item)
            continue
        claims = []
        for match in _CLAUSE.finditer(item['value']):
            clause = match.group().strip()
            marker = _NEGATIVE.search(clause)
            if marker:
                claims.append(clause[marker.start():])
        citations = [cite['quote'] for cite in item.get('citations', ()) if cite['field'] == 'user']
        if not claims or all(any(claim in quote for quote in citations) for claim in claims):
            scoped.append(item)
            continue
        refs = ','.join(map(str, item['source_turns']))
        pending = {key: value for key, value in item.items() if key != 'value'}
        pending.update(kind='PENDING_BINDING', reason='negative_claim_source_unverified',
                       text=f'[PENDING_BINDING] {item["entity"]} / {item["slot"]}；否定状态未由所引用户原文确认；来源轮次 {refs}')
        scoped.append(pending)
    return scoped
