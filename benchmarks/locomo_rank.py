"""Ranking and write-side date support for the Locomo-Plus adapter.

Two problems this module addresses without touching the engine:

* Dates never survive extraction: only 20 of 1043 values carry a year, so a temporal
  question cannot match any value. ``date_suffix`` stamps the session date onto the
  value at write time, where both lexical and vector recall can see it.
* Top-K is a fixed budget, so ranking quality decides what fills it. ``rank`` scores
  candidates by IDF-weighted token overlap over weighted fields, rewards exact date
  and number matches, and caps how many slots one entity may occupy, so a single
  chatty entity cannot crowd out the other facts a multi-hop question needs.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

_MONTHS = ("january february march april may june july august september october "
           "november december").split()


def tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", str(text).lower()) if len(token) > 2}


def date_suffix(date: str) -> str:
    """``1:56 pm on 8 May, 2023`` -> `` on 8 May 2023``; empty when nothing parses."""
    match = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", str(date))
    if not match:
        return ""
    day, month, year = match.groups()
    return f" on {day} {month} {year}" if month.lower() in _MONTHS else ""


_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_DATE_TOKENS = set(_MONTHS) | _WEEKDAYS | {str(year) for year in range(2015, 2031)}


def is_temporal(question: str) -> bool:
    return bool(re.search(r"\b(when|what date|what day|how long|which month|which year|how many (days|weeks|months|years))\b",
                          str(question).lower()))


def date_phrase(date: str) -> str:
    """``8 May 2023`` — the form a temporal question would use, for the topic index."""
    match = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", str(date))
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{day} {month} {year}" if month.lower() in _MONTHS else ""


def document_frequency(values: dict[str, str]) -> Counter:
    frequency: Counter = Counter()
    for value in values.values():
        frequency.update(tokens(value))
    return frequency


def _idf(frequency: Counter, total: int):
    def weight(token: str) -> float:
        return math.log(1 + total / (1 + frequency.get(token, 0)))
    return weight


def rank(pool: list[dict], question: str, values: dict[str, str],
         frequency: Counter, limit: int = 12, per_entity: int = 2) -> list[dict]:
    """IDF-weighted rerank with a per-entity cap; ``per_entity`` guards the fixed budget."""
    query = tokens(question)
    if os.environ.get("WSC_LOCOMO_V4", "").strip().lower() in {"1", "true", "yes", "on"} \
            and not is_temporal(question):
        # 日期词元只在问时间时是证据；否则它们把无关的带日期记忆拉进候选。
        query -= _DATE_TOKENS
    weight = _idf(frequency, max(1, len(values)))
    query_numbers = {token for token in query if token.isdigit()}

    def score(item: dict) -> float:
        entity = tokens(item.get("entity") or "")
        slot = tokens(item.get("slot") or "")
        value = tokens(item.get("value") or "")
        shared = query & (entity | slot | value)
        # An identity word says more about which memory is meant than the same word in prose.
        total = sum(weight(token) * (2.0 if token in entity or token in slot else 1.0)
                    for token in shared)
        exact = 2.0 * len(query_numbers & (value | slot))
        return total + 0.3 * len(shared) + exact + 0.15 * float(item.get("score") or 0)

    ordered = sorted(pool, key=score, reverse=True)
    chosen: list[dict] = []
    per: Counter = Counter()
    for item in ordered:
        entity = str(item.get("entity") or "").lower()
        if per[entity] >= per_entity:
            continue
        per[entity] += 1
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def rank_bm25(pool: list[dict], question: str, values: dict[str, str],
              frequency: Counter, limit: int = 12, per_entity: int = 99,
              matched: list[str] | None = None,
              k1: float = 1.2, b: float = 0.75, topic_boost: float = 1.6) -> list[dict]:
    """BM25 打分：长度归一让长事实不再被稀释，命中 topics 的关键词额外加权。"""
    query = tokens(question)
    weight = _idf(frequency, max(1, len(values)))
    lengths = [len(tokens(text)) for text in values.values()]
    average = sum(lengths) / max(1, len(lengths))
    numbers = {token for token in query if token.isdigit()}

    def topics_of(item: dict) -> set[str]:
        raw = item.get("topics")
        if isinstance(raw, (list, tuple)):
            return tokens(" ".join(str(value) for value in raw))
        return tokens(str(raw or ""))

    def score(item: dict) -> float:
        value = tokens(item.get("value") or "")
        slot = tokens(item.get("slot") or "")
        entity = tokens(item.get("entity") or "")
        topics = topics_of(item)
        length = max(1, len(value))
        total = 0.0
        for token in query & (value | slot | entity | topics):
            tf = 1 + int(token in slot) + int(token in entity) + int(token in topics)
            norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / max(1.0, average)))
            boost = 2.0 if token in slot or token in entity else 1.0
            if token in topics:
                boost *= topic_boost
            total += weight(token) * norm * boost
        return total + 2.0 * len(numbers & (value | slot)) + 0.15 * float(item.get("score") or 0)

    ordered = sorted(pool, key=score, reverse=True)
    chosen: list[dict] = []
    picked: set[str] = set()
    seen_values: list[set[str]] = []

    def redundant(item: dict) -> bool:
        current = tokens(item.get("value") or "")
        for other in seen_values:
            union = len(current | other) or 1
            if len(current & other) / union >= 0.7:
                return True
        return False

    def take(item: dict) -> None:
        chosen.append(item)
        picked.add(item["memory_id"])
        seen_values.append(tokens(item.get("value") or ""))

    if matched and len(matched) >= 2:
        # 多实体问题：先给每个被问到的实体留名额，否则一个实体的记忆会把窗口占满。
        quota = max(2, limit // len(matched))
        for name in matched:
            got = 0
            for item in ordered:
                if item["memory_id"] in picked or str(item.get("entity") or "").lower() != str(name).lower():
                    continue
                if redundant(item):
                    continue
                take(item)
                got += 1
                if got >= quota or len(chosen) >= limit:
                    break
    per: Counter = Counter()
    for item in ordered:
        if len(chosen) >= limit:
            break
        if item["memory_id"] in picked:
            continue
        entity = str(item.get("entity") or "").lower()
        if per[entity] >= per_entity or redundant(item):
            continue
        per[entity] += 1
        take(item)
    if len(chosen) < limit:
        # 去重过度时用剩余条目补满，窗口不空着。
        for item in ordered:
            if len(chosen) >= limit:
                break
            if item["memory_id"] not in picked:
                take(item)
    return chosen[:limit]


def normalize_query(question: str, aliases: dict[str, str], entities: list[str]) -> str:
    """查询规范化：别名与指代补回真实实体名，避免“Mel”这类写法召回不到 Melanie 的记忆。"""
    text = str(question)
    lowered = text.lower()
    extra: list[str] = []
    for alias, entity in (aliases or {}).items():
        if alias and re.search(rf"\b{re.escape(alias.lower())}\b", lowered):
            extra.append(entity)
    for name in entities or []:
        first = str(name).split()[0].lower()
        if len(first) > 3 and first not in lowered and name not in text:
            continue
    return text + ((" " + " ".join(sorted(set(extra)))) if extra else "")


def match_entities(question: str, entities: list[str], aliases: dict[str, str]) -> list[str]:
    """Entities whose any name token occurs in the question, plus confirmed alias hits."""
    lowered = question.lower()
    query = tokens(question)
    found: list[str] = []
    for name in entities:
        forms = {name.lower()} | {alias.lower() for alias, target in aliases.items()
                                  if target == name}
        if any(form and (form in lowered or tokens(form) & query) for form in forms):
            if name not in found:
                found.append(name)
    return found
