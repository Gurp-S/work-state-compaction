"""Resolve a reported comparison back to a visible user observation candidate."""
import re

from bench22.systems import tokens


_DIGITS = r'0-9零〇一二两三四五六七八九十百千万'
_UNITS = r'公斤|千克|公里|小时|分钟|摄氏度|厘米|毫升|元|度|斤|米|步'
_MEASUREMENT = (rf'(?<![{_DIGITS}.])(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+)'
                rf'\s*(?:{_UNITS})'
                rf'(?:半|[一二两三四五六七八九](?![{_DIGITS}]))?(?![{_DIGITS}半])')
_MENTION = re.compile(_MEASUREMENT)
_PAST_COMPARISON = re.compile(r'(?:上回|上次|之前|原来|以前)[^。！？\n，,；;]{0,8}?('
                              + _MEASUREMENT + ')')
_UNIT = re.compile(_UNITS)


def measurement_pair(earlier, later):
    """Require distinct source literals of the same measurement unit."""
    values = [set(_MENTION.findall(text)) for text in (earlier, later)]
    if any(len(value) != 1 for value in values):
        return None
    before, after = (next(iter(value)) for value in values)
    if before != after and _UNIT.search(before)[0] == _UNIT.search(after)[0]:
        return before, after
    return None


def locate_previous_observation(anchor, reply, ranked, turns, visible):
    """Assistant comparisons are search leads; only earlier user text is returned."""
    phrases = set(_PAST_COMPARISON.findall(turns[reply]['assistant']))
    if len(phrases) != 1:
        return None
    phrase, = phrases
    anchor_terms = {token for token in tokens(turns[anchor]['user']) if len(token) >= 2}
    matches = []
    for index in ranked:
        if index not in visible or index >= anchor or visible[index] >= visible[anchor]:
            continue
        text = turns[index]['user']
        if not any(match.group() == phrase for match in _MENTION.finditer(text)):
            continue
        overlap = anchor_terms.intersection(tokens(text.replace(phrase, '')))
        if len(overlap) >= 2:
            matches.append((len(overlap), index))
    matches.sort(reverse=True)
    if not matches or len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][1]
