"""把抽取出的属性名归并到同一实体已有的写法上。

抽取器每次都会给同一个属性起略不同的名字（"灯批检查耗时" / "检查灯耗时" /
"材质" / "遮光材料材质"），于是同一件事被写成多个身份：既查不到，也没法用新值
覆盖旧值。归并只发生在写法层面，事实本身仍由抽取给出。

v2 规则（``WSC_CSM_SLOT_NORM=v2``）：

- 包含关系不再自动视为同一写法。中文的泛称槽位（"建议"、"状态"、"称呼"）会被
  包含在任何具体槽位里，旧规则把它们并进先出现的具体槽位，后续无关事实不断覆盖
  同一身份。v2 只有在短名足够具体且字符重合度很高时才接受包含。
- 对“会累积”的槽位（建议、提醒、约定……），新值与已有值明显不同且不是改口时，
  用线索词或日期把这次观察拆成独立槽位，避免一次性的建议/约定互相覆盖。
"""
from __future__ import annotations

import os
import re

GENERIC_HEADS = frozenset({
    "建议", "提醒", "约定", "事项", "询问", "信息", "内容", "计划", "状态", "情况",
    "称呼", "安排", "要求", "提议", "回应", "做法", "行为", "行动", "身份", "偏好",
    "原因", "时间", "地点", "名称", "名字", "数量", "位置",
})

# 这些槽位下的多条事实可以同时成立，不是同一属性的新旧值。
EPISODIC_HEADS = frozenset({
    "建议", "建议做法", "提醒", "约定", "事项", "询问", "信息", "内容", "提议", "回应",
    "要求",
})

_STRIP = re.compile(r"[\s·\-_/、，。；：:（）()\[\]【】]+")


def version() -> str:
    return os.environ.get("WSC_CSM_SLOT_NORM", "v1").strip().lower() or "v1"


def _clean(text: str) -> str:
    return _STRIP.sub("", text or "").casefold()


def similarity(left: str, right: str) -> float:
    """v1: 包含关系直接算同一写法；否则按字符重合度。保留给旧调用方。"""
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 1.0
    a, b = set(left), set(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def similarity_v2(left: str, right: str) -> float:
    """v2: 字符重合度为主；包含只在高重合且短名具体时加分。"""
    left, right = _clean(left), _clean(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    a, b = set(left), set(right)
    jaccard = len(a & b) / len(a | b) if (a | b) else 0.0
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if short in long and len(short) >= 3 and short not in GENERIC_HEADS and jaccard >= 0.75:
        return max(jaccard, 0.85)
    return jaccard


def is_episodic(slot: str) -> bool:
    key = _clean(slot)
    return key in EPISODIC_HEADS or key.endswith(("建议", "提醒", "约定"))


def _score(left: str, right: str) -> float:
    return similarity_v2(left, right) if version() == "v2" else similarity(left, right)


def _threshold(threshold: float | None) -> float:
    if threshold is not None:
        return threshold
    return 0.8 if version() == "v2" else 0.6


def normalize(slot: str, existing: set[str] | list[str], threshold: float | None = None) -> str:
    """返回 existing 里与该写法最接近的一个；没有够近的就原样返回。"""
    limit = _threshold(threshold)
    best, score = slot, 0.0
    for candidate in existing:
        value = _score(slot, candidate)
        if value > score:
            best, score = candidate, value
    return best if score >= limit else slot


def best_match(slot: str, existing: set[str] | list[str],
               threshold: float | None = None) -> tuple[str | None, float]:
    """最接近的已有写法与相似度；没有候选时返回 (None, 0.0)。"""
    limit = _threshold(threshold)
    best, score = None, 0.0
    for candidate in existing:
        value = _score(slot, candidate)
        if value > score:
            best, score = candidate, value
    if best is not None and score >= limit:
        return best, score
    return None, score


def _value_overlap(left: str, right: str) -> float:
    """值层面的重合度，只用于判断这是“改口”还是“另一件事”。"""
    a, b = set(_clean(str(left))), set(_clean(str(right)))
    return len(a & b) / len(a | b) if (a | b) else 0.0


def unique_slot(slot: str, value, existing: set[str] | list[str]) -> str:
    """Keep two different one-off facts apart even when their topic word is the same."""
    if slot not in existing:
        return slot
    import hashlib

    suffix = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:4]
    candidate, index = f"{slot}·{suffix}", 2
    while candidate in existing:
        candidate, index = f"{slot}·{suffix}{index}", index + 1
    return candidate


def episodic_slot(slot: str, value, topics, head_value, turn_date: str | None = None) -> str:
    """把累积型槽位下明显不同的一次性事实拆成独立槽位。

    "建议" 下的 77 条不同建议若共用一个身份，后一条会把前一条盖成历史值，按截止
    时点检索就再也读不到。这里只在值明显不同、且不是改口（由调用方判断）时拆分。
    """
    base = _clean(slot)
    if not is_episodic(base) or head_value in (None, ""):
        return slot
    if _value_overlap(value, head_value) >= 0.5:
        return slot
    for topic in topics or []:
        key = _clean(str(topic))
        if (len(key) >= 2 and key not in GENERIC_HEADS and key not in base
                and key not in {"用户", "助手", "她", "他", "我", "你"}):
            if base in key:
                # The clue already carries the head ("睡前建议" + "建议").
                return key
            return f"{key}{base}" if base.endswith(("建议", "提醒", "约定")) else f"{base}·{key}"
    if turn_date:
        return f"{base}·{_clean(turn_date)[:8]}"
    return slot


__all__ = ["similarity", "similarity_v2", "normalize", "best_match", "episodic_slot",
           "unique_slot", "is_episodic", "version", "GENERIC_HEADS", "EPISODIC_HEADS"]
