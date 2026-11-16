"""Order adjacent evidence by explicit continuation before spare-budget neighbors."""
import re


_OPENING = re.compile(r'^\s*(?:[^\n]{0,40}见信如晤[^\n]*\n\s*)?(?:接着|继续)'
                      r'(?:说|(?:白天|上午|下午|刚才|前面|上面)(?:那段|的话|的事)?说)')


def continues_previous(user_text):
    return bool(_OPENING.match(user_text))


def order_direct_with_neighbors(ranked, neighbors, turns):
    neighbors = list(dict.fromkeys(neighbors))
    protected = set()
    for anchor in ranked[:3]:
        for position in (anchor - 1, anchor + 1):
            if position in neighbors and continues_previous(turns[max(anchor, position)]['user']):
                protected.add(position)
    return (ranked[:9] + [pos for pos in neighbors if pos in protected] + ranked[9:14]
            + [pos for pos in neighbors if pos not in protected])
