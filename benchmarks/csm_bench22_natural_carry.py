"""Offer the immediately preceding user topic for explicit follow-ups."""
import re


_FOLLOW_UP = re.compile(r'^\s*(?:那(?:就|个|件|笔|种|这|还|么)|所以|还有|刚才|上一条|上面|接着|继续)')


def previous_user_query(question, turns, visible, tail_start):
    if not _FOLLOW_UP.match(question):
        return ''
    recent = next(reversed(visible), None)
    if recent is None or recent < tail_start:
        return ''
    previous = turns[recent]['user'].strip()
    return previous if 8 <= len(previous) <= 360 else ''
