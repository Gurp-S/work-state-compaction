"""Vocabulary-independent surface conflation for recall, never for identity keys.

Keep CJK characters/bigrams. Latin plural and simple participle endings share
one ranking token, so inflection does not create a hard candidate boundary.
This is lossy search normalization; source text and state values are untouched.
"""
from .retrieval import _terms

# Grammatical question/auxiliary words are not evidence of the requested fact.
# Negation, temporal content words and domain vocabulary remain searchable.
_FUNCTION_WORDS = frozenset("the and for with from this that these those there here "
    "are was were has have had does did what when where which who how would could "
    "should can may its into about than then them they their your you our his her "
    "she him been being will shall of to in on at an as by or be is do".split())

# Grammatical overlap is not evidence about a topic. Negation and event/time
# vocabulary remain searchable; this is never used to rewrite a stored value.
_CJK_FUNCTION = frozenset("我 你 他 她 它 我们 你们 他们 她们 它们 的 地 得 了 吗 呢 啊 呀 "
    "是 在 里 有 把 被 和 与 或 也 都 就 很 这 那 这个 那个 什么 什 么 哪 哪个 哪些 "
    "如何 怎么 怎样 为何 是否 当时 时候 情况".split())


def terms(text: str) -> set[str]:
    result = set()
    for token in _terms(text.replace("_", " ")):
        if token in _FUNCTION_WORDS or token in _CJK_FUNCTION:
            continue
        if token.isascii() and token.isalpha():
            if len(token) > 5 and token.endswith("ing"):
                token = token[:-3]
                if len(token) > 2 and token[-1] == token[-2] and not token.endswith("ss"):
                    token = token[:-1]
            elif len(token) > 5 and token.endswith("ed"):
                token = token[:-2]
            elif len(token) > 4 and token.endswith("ies"):
                token = token[:-3] + "y"
            elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
                token = token[:-1]
        result.add(token)
    return result


def query_terms(text: str, bags: list[set[str]]) -> set[str]:
    """Prefer actual CJK word fragments; use character fallback only if needed.

    Single characters remain useful for queries such as '住几楼' versus '四楼'.
    They must not compete with an available informative bigram match such as a
    name or topic merely because incidental prose shares one character.
    """
    wanted = terms(text)
    bigrams = {t for t in wanted if len(t) == 2 and not t.isascii()}
    available = set().union(*(bigrams & bag for bag in bags)) if bags else set()
    # A generic phrase elsewhere in the corpus must not disable a different
    # character's only recall route ('说过住几楼' still needs 楼 -> 四楼).
    return {t for t in wanted if len(t) > 1 or t.isascii()
            or not any(t in fragment for fragment in available)}
